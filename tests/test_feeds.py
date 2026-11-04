"""T1/T2: parsers against data cut from the real sources, and HTTP behaviour against a local server."""
import json
from datetime import datetime, timezone

import pytest

from conftest import commlink_payload, fixture_bytes

TZ = "Asia/Bangkok"


def test_commlink_parses_real_fixture():
    from bot.feeds import sc_commlink

    items = sc_commlink.parse(json.loads(fixture_bytes("commlink.json")), TZ)
    first = next(i for i in items if i.id == "21431")
    assert first.feed == "sc_commlink"
    assert first.kind == "commlink"
    assert first.title == "This Week in Star Citizen"
    assert first.url == "https://robertsspaceindustries.com/en/comm-link/transmission/21431-This-Week-In-Star-Citizen"
    assert "Transmission" in first.description
    assert first.timestamp == datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
    assert first.image and first.image.startswith("https://robertsspaceindustries.com/i/")


def test_commlink_thai_time():
    from bot.feeds import sc_commlink

    items = sc_commlink.parse(json.loads(fixture_bytes("commlink.json")), TZ)
    first = next(i for i in items if i.id == "21431")
    assert "2026-11-03 03:00" in first.description  # 20:00 UTC is 03:00 next day in UTC+7


def test_commlink_without_image_has_none():
    from bot.feeds import sc_commlink

    items = sc_commlink.parse(json.loads(commlink_payload([5])), TZ)
    assert items[0].image is None


@pytest.mark.parametrize(
    "body",
    [{"data": []}, {"nope": 1}, {"data": "x"}, {"data": [{"id": 1}]}, {"data": [{"title": "no id"}]}],
)
def test_commlink_bad_data_raises(body):
    from bot.feeds import FeedError, sc_commlink

    with pytest.raises(FeedError):
        sc_commlink.parse(body, TZ)


def test_status_parses_real_fixture():
    from bot.feeds import sc_status

    items = sc_status.parse(fixture_bytes("status.xml").decode("utf-8"), TZ)
    first = items[0]
    assert first.feed == "sc_status"
    assert first.kind == "status"
    assert first.id == "https://status.robertsspaceindustries.com/issues/2026-10-21_rsi-platform-maintenance/"
    assert first.title == "RSI Platform Maintenance"  # the [Resolved] prefix moves into the description
    assert first.url == "https://status.robertsspaceindustries.com/issues/2026-10-21_rsi-platform-maintenance/index.html"
    assert "Resolved" in first.description
    assert "2026-10-21 21:30" in first.description  # 14:30 UTC is 21:30 in UTC+7
    assert first.timestamp == datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc)
    assert len(items) == 3


def synthetic_rss(title, guid="https://status.example.test/issues/x/"):
    # SYNTHETIC: every real item seen so far is [Resolved]; the real form of an open incident is unknown.
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>RSI Status</title>'
        f"<item><title>{title}</title><link>https://status.example.test/issues/x/index.html</link>"
        f"<pubDate>Wed, 04 Nov 2026 00:00:00 +0000</pubDate><guid>{guid}</guid></item></channel></rss>"
    )


def test_status_without_prefix_does_not_claim_resolved():
    from bot.feeds import sc_status

    item = sc_status.parse(synthetic_rss("Live Services Disruption"), TZ)[0]
    assert item.title == "Live Services Disruption"
    assert "Resolved" not in item.description


def test_status_guid_is_stable_when_status_changes():
    from bot import state
    from bot.feeds import sc_status

    open_item = sc_status.parse(synthetic_rss("[Investigating] Outage"), TZ)
    closed_item = sc_status.parse(synthetic_rss("[Resolved] Outage"), TZ)
    data = {"version": 1, "feeds": {}}
    state.bootstrap(data, "sc_status", open_item)
    assert state.new_items(data, "sc_status", closed_item) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "<html><body>maintenance page</body></html>",
        '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>',
        "<rss><channel><item><title>broken",
    ],
    ids=["empty", "html", "no-items", "truncated"],
)
def test_status_bad_data_raises(text):
    from bot.feeds import FeedError, sc_status

    with pytest.raises(FeedError):
        sc_status.parse(text, TZ)


def test_http_constants_match_requirement():
    from bot import feeds

    assert feeds.TIMEOUT == 15
    assert feeds.RETRIES == 2


def test_retries_twice_then_raises(server, monkeypatch):
    from bot import feeds

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/x", (500, {}, b"boom"))
    with pytest.raises(feeds.FeedError):
        feeds.request_with_retry("GET", server.base + "/x")
    assert len(server.gets("/x")) == 3  # first try + 2 retries


def test_retry_recovers_after_failure(server, monkeypatch):
    from bot import feeds

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/x", (500, {}, b"boom"), (200, {}, b"ok"))
    assert feeds.request_with_retry("GET", server.base + "/x").text == "ok"


def test_404_is_not_retried(server, monkeypatch):
    from bot import feeds

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/x", (404, {}, b"no"))
    with pytest.raises(feeds.FeedError):
        feeds.request_with_retry("GET", server.base + "/x")
    assert len(server.gets("/x")) == 1


def test_every_request_uses_the_timeout(server, monkeypatch):
    import requests

    from bot import feeds

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/x", (200, {}, b"ok"))
    seen = {}
    real = requests.request

    def spy(method, url, **kwargs):
        seen.update(kwargs)
        return real(method, url, **kwargs)

    monkeypatch.setattr(requests, "request", spy)
    feeds.request_with_retry("GET", server.base + "/x")
    assert seen["timeout"] == 15


def test_slow_server_times_out(server, monkeypatch):
    from bot import feeds

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    monkeypatch.setattr(feeds, "TIMEOUT", 0.2)
    server.route("/slow", (200, {}, b"late", 1))
    with pytest.raises(feeds.FeedError):
        feeds.request_with_retry("GET", server.base + "/slow")
    assert len(server.gets("/slow")) == 3


def test_fetch_uses_http_and_returns_items(server):
    from bot.feeds import sc_commlink, sc_status

    server.route("/c", (200, {}, fixture_bytes("commlink.json")))
    server.route("/s", (200, {}, fixture_bytes("status.xml")))
    assert len(sc_commlink.fetch(server.base + "/c", TZ)) == 2
    assert len(sc_status.fetch(server.base + "/s", TZ)) == 3


def test_fetch_bad_json_raises(server):
    from bot.feeds import FeedError, sc_commlink

    server.route("/c", (200, {}, b"<html>not json</html>"))
    with pytest.raises(FeedError):
        sc_commlink.fetch(server.base + "/c", TZ)
