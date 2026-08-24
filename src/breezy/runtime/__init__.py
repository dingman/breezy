"""Runtime wiring: settings, node composition, health/alerting, logging.

Curates the genuine cross-module public surface. Deliberately omits:

* ``breezy.runtime.cli`` (``run``/``main``/``EXIT_*``) -- the process
  entrypoint, an "endpoint helper" per the standard's exclusion, not a
  library surface other modules import.
* ``breezy.runtime.sqlite_store`` -- owned by a concurrent change in this
  session; re-exporting it here would couple this facade to in-flight work.
  Callers that need ``SqliteStateStore`` already import it directly from
  ``breezy.runtime.sqlite_store``.
* ``bootstrap_witness.WITNESS_STORE_KEY`` / ``WITNESS_FILENAME`` -- no
  cross-module caller reaches for the raw constants (only the
  ``witness_file_path``/``enforce_bootstrap_witness`` functions), so they
  stay module-private to this facade.
"""

from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness, witness_file_path
from breezy.runtime.composition import (
    BreezyIngestRuntime,
    build_ingest_actors,
    build_ingest_node,
    ingest_runtime,
    load_site_registry,
    site_snapshot_path,
    site_stagger_offset_seconds,
)
from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    ALLOWED_ALERT_PAYLOAD_KEYS,
    DEFAULT_RENOTIFY_AFTER_NS,
    MAX_ALERT_DETAIL_CHARS,
    SCHEMA_VERSION,
    AlertCondition,
    AlertConditionKey,
    AlertPayload,
    AlertSink,
    AlertState,
    GapSummary,
    HealthSnapshot,
    LoggingAlertSink,
    SiteHealth,
    WebhookAlertSink,
    emit_alert,
    resolve_alert_sink,
    write_snapshot_atomic,
)
from breezy.runtime.logging_bridge import BREEZY_LOGGER_NAME, NautilusLoggingBridgeHandler
from breezy.runtime.logging_bridge import install as install_logging_bridge
from breezy.runtime.logging_bridge import uninstall as uninstall_logging_bridge
from breezy.runtime.node_config import (
    NWS_INGEST_ACTOR_CONFIG_PATH,
    NWS_INGEST_ACTOR_PATH,
    NodeConfigError,
    actor_component_id,
    build_node_config,
    validated_trader_id,
)
from breezy.runtime.settings import BreezyRuntimeSettings, SettingsError, load_settings

__all__ = [
    "ALERT_WEBHOOK_URL_ENV_VAR",
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "BREEZY_LOGGER_NAME",
    "DEFAULT_RENOTIFY_AFTER_NS",
    "MAX_ALERT_DETAIL_CHARS",
    "NWS_INGEST_ACTOR_CONFIG_PATH",
    "NWS_INGEST_ACTOR_PATH",
    "SCHEMA_VERSION",
    "AlertCondition",
    "AlertConditionKey",
    "AlertPayload",
    "AlertSink",
    "AlertState",
    "BreezyIngestRuntime",
    "BreezyRuntimeSettings",
    "GapSummary",
    "HealthSnapshot",
    "LoggingAlertSink",
    "NautilusLoggingBridgeHandler",
    "NodeConfigError",
    "SettingsError",
    "SiteHealth",
    "WebhookAlertSink",
    "actor_component_id",
    "build_ingest_actors",
    "build_ingest_node",
    "build_node_config",
    "emit_alert",
    "enforce_bootstrap_witness",
    "ingest_runtime",
    "install_logging_bridge",
    "load_settings",
    "load_site_registry",
    "resolve_alert_sink",
    "site_snapshot_path",
    "site_stagger_offset_seconds",
    "uninstall_logging_bridge",
    "validated_trader_id",
    "witness_file_path",
    "write_snapshot_atomic",
]
