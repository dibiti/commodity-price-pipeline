"""Unit tests for the alerting module.

These are the project's first tests, and the alerter is a good place to start:
its core is a pure function (Alert -> dict) that needs no network, and its one
side effect (an HTTP POST) is easy to fake. So we can fully verify alerting
behaviour with no Discord account and no real requests.
"""

import requests

from src.pipeline.alerting.alerter import Alert, DiscordAlerter, build_discord_payload


def _sample_alert(**overrides) -> Alert:
    """A representative failed-run alert; individual fields overridable."""
    defaults = dict(
        severity="CRITICAL",
        pipeline_name="commodity_daily",
        error_type="DataQualityError",
        error_message="required field(s) contain null/NaN: ['price']",
        timestamp="2026-08-11T09:00:00+00:00",
        latency_ms=47,
        run_id="11111111-1111-1111-1111-111111111111",
        simulated=True,
    )
    defaults.update(overrides)
    return Alert(**defaults)


class _FakeResponse:
    def __init__(self, status_code: int = 204):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    """Records the last POST instead of sending it over the network."""

    def __init__(self, *, response=None, raises=None):
        self._response = response or _FakeResponse()
        self._raises = raises
        self.last_call: dict | None = None

    def post(self, url, json=None, timeout=None):
        self.last_call = {"url": url, "json": json, "timeout": timeout}
        if self._raises is not None:
            raise self._raises
        return self._response


# ── The pure payload builder ────────────────────────────────────────────────


def test_payload_has_the_key_fields():
    payload = build_discord_payload(_sample_alert())
    embed = payload["embeds"][0]

    assert "CRITICAL" in embed["title"]
    assert "commodity_daily" in embed["title"]

    field_values = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_values["Error type"] == "DataQualityError"
    assert field_values["Latency"] == "47 ms"
    assert field_values["Simulated"] == "yes"
    assert embed["timestamp"] == "2026-08-11T09:00:00+00:00"


def test_payload_marks_a_simulated_run_in_the_title():
    payload = build_discord_payload(_sample_alert(simulated=True))
    assert "simulated" in payload["embeds"][0]["title"]


def test_payload_handles_missing_latency():
    payload = build_discord_payload(_sample_alert(latency_ms=None))
    field_values = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
    assert field_values["Latency"] == "n/a"


# ── The sender ──────────────────────────────────────────────────────────────


def test_send_without_webhook_does_not_post():
    session = _FakeSession()
    alerter = DiscordAlerter("", session=session)

    assert alerter.send(_sample_alert()) is False
    assert session.last_call is None  # nothing was sent


def test_send_with_webhook_posts_the_payload():
    session = _FakeSession(response=_FakeResponse(204))
    alerter = DiscordAlerter("https://discord.test/webhook", session=session)

    assert alerter.send(_sample_alert()) is True
    assert session.last_call["url"] == "https://discord.test/webhook"
    assert session.last_call["json"]["embeds"][0]["title"].startswith("[CRITICAL]")
    assert session.last_call["timeout"] is not None  # a timeout is always set


def test_send_never_raises_when_the_webhook_fails():
    # A network error out of the session must not escape send().
    session = _FakeSession(raises=requests.ConnectionError("boom"))
    alerter = DiscordAlerter("https://discord.test/webhook", session=session)

    assert alerter.send(_sample_alert()) is False  # returns, does not raise
