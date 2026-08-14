"""Best-effort failure alerting to a Discord webhook.

Alerting sits ON TOP of the audit log, never in place of it. By the time we try
to alert, the run's outcome is already durably recorded in
ops.etl_execution_logs — so if the webhook is slow, down, or simply not
configured, we lose a notification, never a record. That ordering (persist
first, notify second) is deliberate: the database is the source of truth; the
alert is a courtesy on top.

The alerter is also OPTIONAL. With no webhook URL, send() logs the alert instead
of posting it, so the whole pipeline runs — and is fully testable — with no
secrets at all.
"""

import logging
from dataclasses import dataclass

import requests

log = logging.getLogger("pipeline.alerting")

# Discord accepts a decimal colour for an embed's side stripe. Red for critical.
_CRITICAL_COLOR = 0xE01E5A

# Discord rejects embed field values longer than 1024 characters, so long error
# messages are truncated to stay well under that.
_MAX_FIELD = 1000


@dataclass(frozen=True)
class Alert:
    """Everything a human needs to triage a failed run at a glance.

    A plain data object, deliberately decoupled from how it is delivered — the
    same Alert could feed Discord, Slack, email or a test, unchanged.
    """

    severity: str
    pipeline_name: str
    error_type: str
    error_message: str
    timestamp: str  # ISO 8601
    latency_ms: int | None
    run_id: str
    simulated: bool


def build_discord_payload(alert: Alert) -> dict:
    """Turn an Alert into a Discord webhook JSON body (a rich "embed").

    Kept as a pure function — Alert in, dict out, no I/O — so the exact shape of
    the message can be unit-tested with no network at all.
    """
    title = f"[{alert.severity}] {alert.pipeline_name} failed"
    if alert.simulated:
        title += "  (simulated)"

    latency = f"{alert.latency_ms} ms" if alert.latency_ms is not None else "n/a"

    return {
        "username": "Pipeline Sentinel",
        "embeds": [
            {
                "title": title,
                "color": _CRITICAL_COLOR,
                "timestamp": alert.timestamp,
                "fields": [
                    {"name": "Pipeline", "value": alert.pipeline_name, "inline": True},
                    {"name": "Error type", "value": alert.error_type, "inline": True},
                    {"name": "Latency", "value": latency, "inline": True},
                    {"name": "Run ID", "value": alert.run_id, "inline": False},
                    {
                        "name": "Detail",
                        "value": alert.error_message[:_MAX_FIELD],
                        "inline": False,
                    },
                    {
                        "name": "Simulated",
                        "value": "yes" if alert.simulated else "no",
                        "inline": True,
                    },
                ],
            }
        ],
    }


class DiscordAlerter:
    def __init__(
        self,
        webhook_url: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 5.0,
    ):
        self._webhook_url = webhook_url
        # An injectable session so tests can pass a fake with no real network.
        self._session = session or requests.Session()
        self._timeout = timeout

    def send(self, alert: Alert) -> bool:
        """Attempt to deliver an alert. NEVER raises.

        Returns True if the webhook accepted it, False otherwise. A False here is
        a missed notification, not a pipeline failure — the caller carries on,
        because the run's outcome is already safe in the audit table.
        """
        payload = build_discord_payload(alert)

        if not self._webhook_url:
            # No webhook configured: log the alert so it is still visible, and
            # treat that as the expected zero-secrets path (not an error).
            log.warning(
                "ALERT (not sent, no webhook set): %s", payload["embeds"][0]["title"]
            )
            return False

        try:
            response = self._session.post(
                self._webhook_url, json=payload, timeout=self._timeout
            )
            response.raise_for_status()
            log.info("Alert delivered for run %s", alert.run_id)
            return True
        except requests.RequestException as exc:
            # The webhook is the thing that failed — so we cannot rely on it to
            # tell anyone. Fall back to the local log and move on.
            log.error("Failed to deliver alert for run %s: %s", alert.run_id, exc)
            return False
