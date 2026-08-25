"""A minimal RFC 6455 loopback WebSocket server for adapter tests.

Why hand-rolled rather than the ``websockets`` library: ``websockets`` reaches
this tree only through the optional ``polymarket-us`` extra (``uv.lock``:
``polymarket-us`` -> ``websockets``). A test that imports it would have to
``importorskip``, and a guard that silently skips on a default checkout is
indistinguishable from a guard that passes -- the same reasoning that moved
``pynacl`` into the core dependencies. This server has no dependencies beyond
the standard library.

It implements exactly the subset the adapter exercises: the HTTP upgrade
handshake (recording every request header, which is what the fresh-signature
assertions read), masked text frames client->server, unmasked text frames
server->client, ping/pong, and close. It is deliberately not a general-purpose
server.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from enum import Enum
from types import TracebackType
from typing import Self

_WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_OPCODE_TEXT = 0x1
_OPCODE_CLOSE = 0x8
_OPCODE_PING = 0x9
_OPCODE_PONG = 0xA


class ServerMode(Enum):
    """How the server treats a newly accepted TCP connection."""

    ACCEPT = "accept"
    #: Accept the TCP connection, then abort it before the upgrade completes.
    #: Models a venue that refuses the handshake (e.g. a rejected signature).
    REFUSE_HANDSHAKE = "refuse_handshake"


class LoopbackWebSocketServer:
    """A 127.0.0.1 WebSocket server that records what clients send it."""

    def __init__(self, *, mode: ServerMode = ServerMode.ACCEPT) -> None:
        self.mode = mode
        #: One dict of lower-cased request headers per completed handshake.
        self.handshakes: list[dict[str, str]] = []
        #: Text payloads received from clients, in arrival order.
        self.messages: list[str] = []
        #: Every accepted TCP connection, including refused handshakes.
        self.connection_attempts: int = 0
        self.port: int = 0
        self._server: asyncio.base_events.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        sockets = self._server.sockets
        assert sockets, "loopback server bound no socket"
        self.port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        self.drop_connections()
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()

    def drop_connections(self) -> None:
        """Abort every live connection without a close handshake."""
        for writer in self._writers:
            writer.transport.abort()
        self._writers.clear()

    async def push_text(self, payload: str) -> None:
        for writer in self._writers:
            writer.write(_frame(_OPCODE_TEXT, payload.encode("utf-8")))
            await writer.drain()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connection_attempts += 1
        if self.mode is ServerMode.REFUSE_HANDSHAKE:
            writer.transport.abort()
            return
        try:
            request = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionResetError):
            writer.close()
            return

        headers = _parse_headers(request)
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1(key.encode("ascii") + _WS_GUID).digest())
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        await writer.drain()
        self.handshakes.append(headers)
        self._writers.append(writer)
        await self._read_frames(reader, writer)

    async def _read_frames(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                opcode, payload = await _read_frame(reader)
                if opcode == _OPCODE_TEXT:
                    self.messages.append(payload.decode("utf-8"))
                elif opcode == _OPCODE_PING:
                    writer.write(_frame(_OPCODE_PONG, payload))
                    await writer.drain()
                elif opcode == _OPCODE_CLOSE:
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            if writer in self._writers:
                self._writers.remove(writer)
            writer.close()


def _parse_headers(request: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in request.decode("latin-1").split("\r\n")[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = int(struct.unpack("!H", await reader.readexactly(2))[0])
    elif length == 127:
        length = int(struct.unpack("!Q", await reader.readexactly(8))[0])
    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    payload = bytearray(await reader.readexactly(length))
    for index in range(length):
        payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


def _frame(opcode: int, payload: bytes) -> bytes:
    size = len(payload)
    if size < 126:
        header = struct.pack("!BB", 0x80 | opcode, size)
    elif size < 1 << 16:
        header = struct.pack("!BBH", 0x80 | opcode, 126, size)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, size)
    return header + payload
