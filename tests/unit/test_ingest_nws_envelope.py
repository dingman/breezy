"""Tests for `breezy.ingest.nws_envelope`.

Fixtures below use realistic dicts shaped exactly like the live
api.weather.gov responses verified this session:

* Discovery: `GET /products/types/CLI/locations/NYC` -> `{"@graph": [...]}`,
  each entry carrying `id`, `wmoCollectiveId`, `issuingOffice`,
  `issuanceTime`, `productCode`, `productName`.
* Product: `GET /products/{id}` -> the same metadata keys plus
  `productText`.

No network is used or needed -- these are pure in-memory dict fixtures, and
the autouse socket-blocking fixture in `tests/conftest.py` would refuse a
real connection anyway.
"""

from __future__ import annotations

from typing import Any

import pytest

from breezy.ingest.nws_envelope import (
    DiscoveryEntry,
    NwsEnvelopeFieldError,
    NwsEnvelopeStructureError,
    NwsEnvelopeTimestampError,
    NwsEnvelopeUuidError,
    ProductEnvelope,
    parse_discovery_list,
    parse_iso8601_to_ns,
    parse_product_envelope,
)

_VALID_UUID = "8f14e45f-ceea-467e-9c62-6c1f6d6e5b0a"
_OTHER_VALID_UUID = "1b7a3c9e-2f4d-4a6b-8c1d-9e0f1a2b3c4d"


def _discovery_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": _VALID_UUID,
        "wmoCollectiveId": "CDUS41",
        "issuingOffice": "KOKX",
        "issuanceTime": "2020-01-01T00:00:00-05:00",
        "productCode": "CLI",
        "productName": "Climate Report (CLI)",
    }
    entry.update(overrides)
    return entry


def _product_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": _VALID_UUID,
        "wmoCollectiveId": "CDUS41",
        "issuingOffice": "KOKX",
        "issuanceTime": "2020-01-01T00:00:00-05:00",
        "productCode": "CLI",
        "productName": "Climate Report (CLI)",
        "productText": "...THE CENTRAL PARK CLIMATE SUMMARY...",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# parse_iso8601_to_ns
# --------------------------------------------------------------------------


class TestParseIso8601ToNs:
    def test_utc_offset_zero_matches_hand_computed_epoch_seconds(self) -> None:
        # 2020-01-01T00:00:00Z is exactly 1577836800 seconds after the epoch
        # (a widely-known reference value, hand-checkable independent of
        # this module: 50 years * 365.2425 days/year * 86400 s/day is in the
        # right ballpark, and 1577836800 is the well-known UNIX timestamp
        # for 2020-01-01T00:00:00Z).
        assert parse_iso8601_to_ns("2020-01-01T00:00:00+00:00") == 1_577_836_800_000_000_000

    def test_negative_offset_shifts_forward_in_utc(self) -> None:
        # 2020-01-01T00:00:00-05:00 is 05:00:00Z the same calendar day:
        # 1577836800 (2020-01-01T00:00:00Z) + 5*3600 = 1577854800 seconds.
        assert parse_iso8601_to_ns("2020-01-01T00:00:00-05:00") == 1_577_854_800_000_000_000

    def test_positive_offset_shifts_backward_in_utc(self) -> None:
        # 2020-01-01T05:00:00+05:00 is 00:00:00Z:
        # 1577836800 - 0 = 1577836800 seconds (the offset exactly cancels
        # the local hour).
        assert parse_iso8601_to_ns("2020-01-01T05:00:00+05:00") == 1_577_836_800_000_000_000

    def test_fractional_seconds_are_preserved_as_nanoseconds(self) -> None:
        # 500000 microseconds = 500,000,000 nanoseconds added to the whole
        # second at 1577836800.
        assert parse_iso8601_to_ns(
            "2020-01-01T00:00:00.500000+00:00"
        ) == 1_577_836_800_500_000_000

    def test_naive_timestamp_is_rejected_not_assumed_utc(self) -> None:
        with pytest.raises(NwsEnvelopeTimestampError):
            parse_iso8601_to_ns("2020-01-01T00:00:00")

    def test_unparseable_timestamp_is_rejected(self) -> None:
        with pytest.raises(NwsEnvelopeTimestampError):
            parse_iso8601_to_ns("not-a-timestamp")

    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(NwsEnvelopeTimestampError):
            parse_iso8601_to_ns("")


# --------------------------------------------------------------------------
# parse_discovery_list
# --------------------------------------------------------------------------


class TestParseDiscoveryList:
    def test_happy_path_returns_one_discovery_entry(self) -> None:
        payload = {"@graph": [_discovery_entry()]}

        result = parse_discovery_list(payload)

        assert result == (
            DiscoveryEntry(
                product_uuid=_VALID_UUID,
                product_code="CLI",
                issuing_office="KOKX",
                wmo_collective_id="CDUS41",
                issuance_time_ns=1_577_854_800_000_000_000,
            ),
        )

    def test_happy_path_multiple_entries_preserves_order(self) -> None:
        payload = {
            "@graph": [
                _discovery_entry(id=_VALID_UUID),
                _discovery_entry(id=_OTHER_VALID_UUID),
            ]
        }

        result = parse_discovery_list(payload)

        assert [entry.product_uuid for entry in result] == [_VALID_UUID, _OTHER_VALID_UUID]

    def test_empty_graph_returns_empty_tuple(self) -> None:
        assert parse_discovery_list({"@graph": []}) == ()

    def test_missing_graph_key_raises_structure_error(self) -> None:
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list({})

    def test_graph_not_a_list_raises_structure_error(self) -> None:
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list({"@graph": {"id": _VALID_UUID}})

    def test_graph_entry_not_an_object_raises_structure_error(self) -> None:
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list({"@graph": ["not-an-object"]})

    def test_graph_exceeding_max_items_raises_structure_error(self) -> None:
        payload = {"@graph": [_discovery_entry() for _ in range(5)]}
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list(payload, max_items=4)

    def test_graph_at_max_items_is_accepted(self) -> None:
        payload = {"@graph": [_discovery_entry() for _ in range(4)]}
        result = parse_discovery_list(payload, max_items=4)
        assert len(result) == 4

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode"],
    )
    def test_missing_required_field_raises_field_error(self, key: str) -> None:
        entry = _discovery_entry()
        del entry[key]
        with pytest.raises(NwsEnvelopeFieldError):
            parse_discovery_list({"@graph": [entry]})

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode"],
    )
    def test_null_required_field_raises_field_error(self, key: str) -> None:
        entry = _discovery_entry(**{key: None})
        with pytest.raises(NwsEnvelopeFieldError):
            parse_discovery_list({"@graph": [entry]})

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode"],
    )
    def test_wrong_typed_required_field_raises_field_error(self, key: str) -> None:
        entry = _discovery_entry(**{key: 12345})
        with pytest.raises(NwsEnvelopeFieldError):
            parse_discovery_list({"@graph": [entry]})

    def test_empty_string_required_field_raises_field_error(self) -> None:
        entry = _discovery_entry(productCode="")
        with pytest.raises(NwsEnvelopeFieldError):
            parse_discovery_list({"@graph": [entry]})

    def test_bad_uuid_shape_raises_uuid_error(self) -> None:
        entry = _discovery_entry(id="not-a-uuid")
        with pytest.raises(NwsEnvelopeUuidError):
            parse_discovery_list({"@graph": [entry]})

    def test_uuid_is_matched_byte_identical_not_normalised(self) -> None:
        # Uppercase hex is a canonical UUID shape but a DIFFERENT string
        # than its lowercase form; the parser must return it verbatim.
        upper = _VALID_UUID.upper()
        entry = _discovery_entry(id=upper)
        result = parse_discovery_list({"@graph": [entry]})
        assert result[0].product_uuid == upper

    def test_naive_issuance_time_raises_timestamp_error(self) -> None:
        entry = _discovery_entry(issuanceTime="2020-01-01T00:00:00")
        with pytest.raises(NwsEnvelopeTimestampError):
            parse_discovery_list({"@graph": [entry]})

    def test_oversize_payload_raises_structure_error_before_walking_fields(self) -> None:
        # A single entry with an absurd number of extra sibling keys blows
        # the total node-count cap; none of the required fields are even
        # malformed here, proving the size cap is checked first.
        huge_entry = _discovery_entry()
        for i in range(20_000):
            huge_entry[f"extra_{i}"] = i
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list({"@graph": [huge_entry]})

    def test_deeply_nested_payload_raises_structure_error(self) -> None:
        nested: dict[str, Any] = {"leaf": 1}
        for _ in range(50):
            nested = {"nested": nested}
        payload = {"@graph": [_discovery_entry(deep=nested)]}
        with pytest.raises(NwsEnvelopeStructureError):
            parse_discovery_list(payload)


# --------------------------------------------------------------------------
# parse_product_envelope
# --------------------------------------------------------------------------


class TestParseProductEnvelope:
    def test_happy_path_returns_product_envelope(self) -> None:
        payload = _product_payload()

        result = parse_product_envelope(payload)

        assert result == ProductEnvelope(
            product_uuid=_VALID_UUID,
            product_code="CLI",
            issuing_office="KOKX",
            wmo_collective_id="CDUS41",
            issuance_time_ns=1_577_854_800_000_000_000,
            product_text="...THE CENTRAL PARK CLIMATE SUMMARY...",
            awips_pil=None,
            wmo_bbb_token=None,
        )

    def test_awips_pil_and_bbb_token_are_read_when_present(self) -> None:
        payload = _product_payload(awipsIdentifier="CLINYC", wmoBBB="CCA")

        result = parse_product_envelope(payload)

        assert result.awips_pil == "CLINYC"
        assert result.wmo_bbb_token == "CCA"

    def test_awips_pil_and_bbb_token_are_none_when_explicitly_null(self) -> None:
        payload = _product_payload(awipsIdentifier=None, wmoBBB=None)

        result = parse_product_envelope(payload)

        assert result.awips_pil is None
        assert result.wmo_bbb_token is None

    def test_wrong_typed_optional_field_raises_field_error(self) -> None:
        payload = _product_payload(awipsIdentifier=42)
        with pytest.raises(NwsEnvelopeFieldError):
            parse_product_envelope(payload)

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode", "productText"],
    )
    def test_missing_required_field_raises_field_error(self, key: str) -> None:
        payload = _product_payload()
        del payload[key]
        with pytest.raises(NwsEnvelopeFieldError):
            parse_product_envelope(payload)

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode", "productText"],
    )
    def test_null_required_field_raises_field_error(self, key: str) -> None:
        payload = _product_payload(**{key: None})
        with pytest.raises(NwsEnvelopeFieldError):
            parse_product_envelope(payload)

    @pytest.mark.parametrize(
        "key",
        ["id", "wmoCollectiveId", "issuingOffice", "issuanceTime", "productCode", "productText"],
    )
    def test_wrong_typed_required_field_raises_field_error(self, key: str) -> None:
        payload = _product_payload(**{key: ["not", "a", "string"]})
        with pytest.raises(NwsEnvelopeFieldError):
            parse_product_envelope(payload)

    def test_bad_uuid_shape_raises_uuid_error(self) -> None:
        payload = _product_payload(id="12345")
        with pytest.raises(NwsEnvelopeUuidError):
            parse_product_envelope(payload)

    def test_naive_issuance_time_raises_timestamp_error(self) -> None:
        payload = _product_payload(issuanceTime="2020-01-01T00:00:00")
        with pytest.raises(NwsEnvelopeTimestampError):
            parse_product_envelope(payload)

    def test_empty_product_text_raises_field_error(self) -> None:
        payload = _product_payload(productText="")
        with pytest.raises(NwsEnvelopeFieldError):
            parse_product_envelope(payload)

    def test_oversize_payload_raises_structure_error(self) -> None:
        payload = _product_payload()
        for i in range(20_000):
            payload[f"extra_{i}"] = i
        with pytest.raises(NwsEnvelopeStructureError):
            parse_product_envelope(payload)

    def test_deeply_nested_payload_raises_structure_error(self) -> None:
        nested: dict[str, Any] = {"leaf": 1}
        for _ in range(50):
            nested = {"nested": nested}
        payload = _product_payload(deep=nested)
        with pytest.raises(NwsEnvelopeStructureError):
            parse_product_envelope(payload)
