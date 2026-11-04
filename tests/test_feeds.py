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
    assert first.description.startswith("Last week, Alpha 4.10.3")
    assert first.category == "Transmission"
    assert first.compact is False
    assert "หมวด" not in first.description
    assert "วันที่" not in first.description
    assert first.timestamp == datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
    assert first.image is None  # the cover comes from the article page, only when an item is about to be sent


def test_summary_from_real_fixture_drops_markup_and_repeated_title():
    from bot.feeds import sc_commlink

    items = sc_commlink.parse(json.loads(fixture_bytes("commlink.json")), TZ)
    jump = next(i for i in items if i.id == "21427")
    assert jump.description.startswith("ISSUE: 14 05")


@pytest.mark.parametrize(
    "title,text,expected",
    [
        ("Day of the Vara 2956 | Star Citizen", "Heap-Thumbnail_Day_Of_The_Vara SOMETHING STIRS IN THE BLACK\n\n\n\nFrozen pilots.", "SOMETHING STIRS IN THE BLACK\nFrozen pilots."),
        ("Digital Goodies Pack | Star Citizen", "SC_DigitalGoodiesBK-Copy RSI_Top_Banner LEGACY. CELEBRATION.\n\nThe year-long event.", "LEGACY. CELEBRATION.\nThe year-long event."),
        ("Promo", "h2 h3 Promo\n\n\nWhether you are celebrating.", "Whether you are celebrating."),
        ("Star Citizen | RSI Discovery Month", "RSI Discovery Month Starts now.", "Starts now."),
        ("Plain", "Nothing to remove here.", "Nothing to remove here."),
    ],
    ids=["file-token", "many-tokens", "markup-and-title", "site-name-in-title", "plain"],
)
def test_summary_cleans_text(title, text, expected):
    from bot.feeds import sc_commlink

    assert sc_commlink.summarize(text, title) == expected


@pytest.mark.parametrize(
    "title,text,expected",
    [
        ("Roadmap Roundup - October 21, 2026", "Roadmap Roundup Hello everyone!\n\nEvery two weeks, we explain changes.", "Every two weeks, we explain changes."),
        ("Roadmap Roundup - October 21, 2026", "Roadmap Roundup Every two weeks, we explain changes.", "Every two weeks, we explain changes."),
        ("This Week", "This Week xē'suelen nyahyan, hello everyone,\nLast week was busy.", "Last week was busy."),
        ("Winners", "The Discover the ship Community Highlights View more on Community Hub By Results\n\nWe have a CHAMPION!", "We have a CHAMPION!"),
    ],
    ids=["dated-title-and-greeting", "dated-title-only", "greeting-after-name", "web-menu-line"],
)
def test_summary_removes_clutter_seen_in_real_articles(title, text, expected):
    from bot.feeds import sc_commlink

    assert sc_commlink.summarize(text, title) == expected


def test_summary_without_a_sentence_is_empty():
    from bot.feeds import sc_commlink

    assert sc_commlink.summarize("Heading Only Words Here", "Title") == ""


def test_summary_ends_at_a_full_sentence():
    from bot.feeds import sc_commlink

    text = "First sentence is here. " + "Second sentence keeps going on. " * 8 + "x" * 200
    summary = sc_commlink.summarize(text, "Title")
    assert len(summary) <= 300
    assert summary.endswith("going on.")


def test_summary_is_limited_at_a_word_boundary():
    from bot.feeds import sc_commlink

    summary = sc_commlink.summarize("word " * 200, "Title")
    assert len(summary) <= 300
    assert summary.endswith("word…")


@pytest.mark.parametrize("text", [None, "", "   ", "h2 h3", "Only_File_Token"], ids=["none", "empty", "spaces", "markup", "token"])
def test_summary_empty_when_nothing_remains(text):
    from bot.feeds import sc_commlink

    assert sc_commlink.summarize(text, "Title") == ""


def row(**changes):
    base = {"id": 7, "title": "R-PU-ORS-Pistol-1", "rsi_url": "https://example.test/promo", "channel": "Undefined",
            "images_count": 0, "translations": None, "created_at": "2026-11-02T20:00:00+00:00"}
    return {**base, **changes}


@pytest.mark.parametrize(
    "changes,compact,category",
    [
        ({}, True, None),
        ({"translations": {"en_EN": "A real article body."}}, False, None),
        ({"images_count": 3}, False, None),
        ({"channel": "Transmission"}, False, "Transmission"),
    ],
    ids=["promo", "has-text", "has-images", "has-category"],
)
def test_compact_only_without_category_text_or_images(changes, compact, category):
    from bot.feeds import sc_commlink

    item = sc_commlink.parse({"data": [row(**changes)]}, TZ)[0]
    assert item.compact is compact
    assert item.category == category


YT = "https://www.youtube.com/watch?v=zNL_FgoTrjA"


@pytest.mark.parametrize(
    "links,expected",
    [
        ([{"href": YT, "text": "x"}], YT),
        ([{"href": "https://youtu.be/zNL_FgoTrjA"}], "https://youtu.be/zNL_FgoTrjA"),
        ([{"href": YT}, {"href": "https://robertsspaceindustries.com/community-hub"}], YT),
        ([{"href": YT}, {"href": YT}], YT),
        ([{"href": YT}, {"href": "https://www.youtube.com/watch?v=d8Qt8YA-Uco"}], None),
        ([{"href": "https://robertsspaceindustries.com/community-hub"}], None),
        ([{"href": "https://youtube.com.evil.test/watch?v=zNL_FgoTrjA"}], None),
        ([{"href": "http://www.youtube.com/watch?v=zNL_FgoTrjA"}], None),
        ([], None),
        (None, None),
    ],
    ids=["one", "short-form", "with-other-link", "duplicate", "two-videos", "not-video", "lookalike", "not-https", "empty", "missing"],
)
def test_video_only_when_exactly_one_youtube_link(links, expected):
    from bot.feeds import sc_commlink

    item = sc_commlink.parse({"data": [row(channel="Transmission", links=links)]}, TZ)[0]
    assert item.video == expected


@pytest.mark.parametrize("video", [YT, "https://youtu.be/zNL_FgoTrjA", YT + "&t=30"], ids=["watch", "short", "extra-params"])
def test_thumbnail_uses_the_best_image_when_available(server, monkeypatch, video):
    from bot.feeds import sc_commlink

    monkeypatch.setattr(sc_commlink, "THUMBNAILS", server.base + "/vi")
    server.route("/vi/zNL_FgoTrjA/maxresdefault.jpg", (200, {}, b"image"))
    assert sc_commlink.video_thumbnail(video) == server.base + "/vi/zNL_FgoTrjA/maxresdefault.jpg"


def test_thumbnail_falls_back_when_the_best_image_is_missing(server, monkeypatch):
    from bot.feeds import sc_commlink

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    monkeypatch.setattr(sc_commlink, "THUMBNAILS", server.base + "/vi")
    server.route("/vi/zNL_FgoTrjA/maxresdefault.jpg", (404, {}, b"none"))
    assert sc_commlink.video_thumbnail(YT) == server.base + "/vi/zNL_FgoTrjA/hqdefault.jpg"


def test_add_covers_uses_the_thumbnail_for_a_video(monkeypatch):
    from bot.feeds import Item, sc_commlink

    opened = []
    monkeypatch.setattr(sc_commlink, "cover_image", lambda url: opened.append(url) or "cover")
    monkeypatch.setattr(sc_commlink, "video_thumbnail", lambda video: "thumb")
    item = Item(id="1", feed="sc_commlink", kind="commlink", title="t", url="https://example.test/1",
                description="d", timestamp=None, image=None, video=YT)
    sc_commlink.add_covers([item])
    assert item.image == "thumb"
    assert opened == []


def test_commlink_without_text_has_empty_description():
    from bot.feeds import sc_commlink

    item = sc_commlink.parse(json.loads(commlink_payload([5])), TZ)[0]
    assert item.description == ""


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


COVER = "https://cdn.example.test/cover.jpg"


@pytest.mark.parametrize(
    "tag",
    [
        f'<meta property="og:image" content="{COVER}">',
        f'<meta content="{COVER}" property="og:image" />',
        f"<META PROPERTY='og:image' CONTENT='{COVER}'>",
    ],
    ids=["property-first", "content-first", "uppercase-single-quotes"],
)
def test_cover_image_reads_og_image(server, tag):
    from bot.feeds import sc_commlink

    html = f'<html><head><meta property="og:title" content="x">{tag}</head></html>'
    server.route("/a", (200, {}, html.encode()))
    assert sc_commlink.cover_image(server.base + "/a") == COVER


def test_cover_image_unescapes_entities(server):
    from bot.feeds import sc_commlink

    server.route("/a", (200, {}, b'<meta property="og:image" content="https://cdn.example.test/c.jpg?a=1&amp;b=2">'))
    assert sc_commlink.cover_image(server.base + "/a") == "https://cdn.example.test/c.jpg?a=1&b=2"


def test_cover_image_none_when_tag_is_missing(server):
    from bot.feeds import sc_commlink

    server.route("/a", (200, {}, b'<html><meta property="og:title" content="x"></html>'))
    assert sc_commlink.cover_image(server.base + "/a") is None


@pytest.mark.parametrize("bad", ["http://cdn.example.test/c.jpg", "javascript:alert(1)", ""], ids=["http", "script", "empty"])
def test_cover_image_rejects_anything_but_https(server, bad):
    from bot.feeds import sc_commlink

    server.route("/a", (200, {}, f'<meta property="og:image" content="{bad}">'.encode()))
    assert sc_commlink.cover_image(server.base + "/a") is None


def test_cover_image_none_when_page_fails(server, monkeypatch):
    from bot.feeds import sc_commlink

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/a", (500, {}, b"boom"))
    assert sc_commlink.cover_image(server.base + "/a") is None


def test_add_covers_stops_at_the_time_limit(monkeypatch):
    from bot.feeds import Item, sc_commlink

    opened = []

    def fake_cover(url):
        opened.append(url)
        return COVER

    monkeypatch.setattr(sc_commlink, "cover_image", fake_cover)
    items = [
        Item(id=str(i), feed="sc_commlink", kind="commlink", title="t", url=f"https://example.test/{i}",
             description="d", timestamp=None, image=None)
        for i in range(3)
    ]
    ticks = iter([0, 10, 60, 60, 60, 60])
    sc_commlink.add_covers(items, budget=60, clock=lambda: next(ticks))
    assert opened == ["https://example.test/0"]
    assert [i.image for i in items] == [COVER, None, None]


def test_fetch_bad_json_raises(server):
    from bot.feeds import FeedError, sc_commlink

    server.route("/c", (200, {}, b"<html>not json</html>"))
    with pytest.raises(FeedError):
        sc_commlink.fetch(server.base + "/c", TZ)
