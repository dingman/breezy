"""Re-export of :mod:`breezy.registry.health_model`.

The implementation moved below ``ingest`` so the NWS actor can import it
without an upward edge into ``runtime``. These names are the same objects,
not copies: a running process that still does ``from breezy.runtime.health
import AlertState`` (or looks the name up on this module) keeps working
until the next restart, and ``is`` comparisons across the two paths hold.

Importing this module therefore imports ``breezy.registry`` (and, via that
package's ``__init__``, ``breezy.registry.sites``). ``sites`` is stdlib-only.
This module must not grow a further ``breezy`` or ``nautilus_trader`` import.

Assignments, not ``import X as X``: mypy's implicit-reexport ban needs an
explicit binding, and a redundant alias is a lint error.
"""

from breezy.registry import health_model as _health_model

ALERT_EGRESS_UNCONFIGURED_EVENT = _health_model.ALERT_EGRESS_UNCONFIGURED_EVENT
ALERT_WEBHOOK_URL_ENV_VAR = _health_model.ALERT_WEBHOOK_URL_ENV_VAR
ALLOWED_ALERT_PAYLOAD_KEYS = _health_model.ALLOWED_ALERT_PAYLOAD_KEYS
DEFAULT_RENOTIFY_AFTER_NS = _health_model.DEFAULT_RENOTIFY_AFTER_NS
FINAL_OVERDUE = _health_model.FINAL_OVERDUE
GAP_RETENTION_WARNING = _health_model.GAP_RETENTION_WARNING
MAX_ALERT_DETAIL_CHARS = _health_model.MAX_ALERT_DETAIL_CHARS
POLL_STALE = _health_model.POLL_STALE
POST_SETTLEMENT_REVISION = _health_model.POST_SETTLEMENT_REVISION
SCHEMA_VERSION = _health_model.SCHEMA_VERSION
SITE_BLOCKED = _health_model.SITE_BLOCKED
SNAPSHOT_DIR_MODE = _health_model.SNAPSHOT_DIR_MODE
SNAPSHOT_FILE_MODE = _health_model.SNAPSHOT_FILE_MODE
UA_TRAP_LATCHED = _health_model.UA_TRAP_LATCHED
AlertCondition = _health_model.AlertCondition
AlertConditionKey = _health_model.AlertConditionKey
AlertPayload = _health_model.AlertPayload
AlertSink = _health_model.AlertSink
AlertState = _health_model.AlertState
GapSummary = _health_model.GapSummary
HealthSnapshot = _health_model.HealthSnapshot
LoggingAlertSink = _health_model.LoggingAlertSink
SiteHealth = _health_model.SiteHealth
TeeAlertSink = _health_model.TeeAlertSink
WebhookAlertSink = _health_model.WebhookAlertSink
alert_egress_configured = _health_model.alert_egress_configured
emit_alert = _health_model.emit_alert
log_alert_egress_status = _health_model.log_alert_egress_status
resolve_alert_sink = _health_model.resolve_alert_sink
write_snapshot_atomic = _health_model.write_snapshot_atomic

__all__ = [
    "ALERT_EGRESS_UNCONFIGURED_EVENT",
    "ALERT_WEBHOOK_URL_ENV_VAR",
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "DEFAULT_RENOTIFY_AFTER_NS",
    "FINAL_OVERDUE",
    "GAP_RETENTION_WARNING",
    "MAX_ALERT_DETAIL_CHARS",
    "POLL_STALE",
    "POST_SETTLEMENT_REVISION",
    "SCHEMA_VERSION",
    "SITE_BLOCKED",
    "SNAPSHOT_DIR_MODE",
    "SNAPSHOT_FILE_MODE",
    "UA_TRAP_LATCHED",
    "AlertCondition",
    "AlertConditionKey",
    "AlertPayload",
    "AlertSink",
    "AlertState",
    "GapSummary",
    "HealthSnapshot",
    "LoggingAlertSink",
    "SiteHealth",
    "TeeAlertSink",
    "WebhookAlertSink",
    "alert_egress_configured",
    "emit_alert",
    "log_alert_egress_status",
    "resolve_alert_sink",
    "write_snapshot_atomic",
]
