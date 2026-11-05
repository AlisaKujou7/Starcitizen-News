"""RSI's own news list: how new articles are found, because the Star Citizen Wiki can lag by days."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import commlink_payload, fixture_bytes

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
TZ = "Asia/Bangkok"


def rsi_block(item_id, title=None, age="4 hours ago", body="A clear summary.", section="transmission"):
    title = title or f"Article {item_id}"
    return (
        f'<a class="content-block2 hub-block full" href="/comm-link/{section}/{item_id}-Article">'
        '<div class="type post"><span>post</span></div>'
        "<div class=\"background\" style=\"background-image:url('https://media.example.test/channel_item_full.jpg');\"></div>"
        f'<div class="title-holder"><div class="title trans-opacity trans-03s">{title}</div></div>'
        f'<div class="text"><div class="time_ago">Posted: <span class="value">{age}</span></div></div>'
        f'<div class="over"><div class="body"><p>{body}</p></div></div></a>'
    )


def rsi_payload(*blocks):
    return json.dumps({"success": 1, "code": "OK", "msg": "OK", "data": "".join(blocks)}).encode()


def test_parses_the_real_list():
    from bot.feeds import sc_commlink

    items = sc_commlink.parse_rsi(json.loads(fixture_bytes("rsi_list.json")), NOW)
    first = items[0]
    assert [i.id for i in items] == ["21432", "21422", "21311"]
    assert first.feed == "sc_commlink"
    assert first.kind == "commlink"
    assert first.title == "Star Citizen Monthly Report: October 2026"
    assert first.url == "https://robertsspaceindustries.com/comm-link/transmission/21432-Star-Citizen-Monthly-Report-October-2026"
    assert first.category == "Transmission"
    assert first.description.startswith("Welcome to October")
    assert first.image.startswith("https://media.robertsspaceindustries.com/")
    assert first.compact is False


def test_summary_is_plain_text_within_the_limit():
    from bot.feeds import sc_commlink

    body = "<b>Bold</b> &amp; spaced   \n  text. " * 40
    item = sc_commlink.parse_rsi(json.loads(rsi_payload(rsi_block(1, body=body))), NOW)[0]
    assert len(item.description) <= 300
    assert item.description.startswith("Bold & spaced text.")
    assert "<" not in item.description


@pytest.mark.parametrize(
    "age,expected",
    [
        ("4 hours ago", timedelta(hours=4)),
        ("1 day ago", timedelta(days=1)),
        ("2 weeks ago", timedelta(weeks=2)),
        ("30 minutes ago", timedelta(minutes=30)),
        ("3 months ago", timedelta(days=90)),
    ],
    ids=["hours", "day", "weeks", "minutes", "months"],
)
def test_age_becomes_a_time(age, expected):
    from bot.feeds import sc_commlink

    item = sc_commlink.parse_rsi(json.loads(rsi_payload(rsi_block(1, age=age))), NOW)[0]
    assert item.timestamp == NOW - expected


def test_unknown_age_has_no_time():
    from bot.feeds import sc_commlink

    item = sc_commlink.parse_rsi(json.loads(rsi_payload(rsi_block(1, age="just now"))), NOW)[0]
    assert item.timestamp is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"success": 0, "data": ""},
        {"success": 0, "data": rsi_block(5)},
        {"success": 1, "data": ""},
        {"success": 1, "data": "<div>we moved</div>"},
        {"success": 1, "data": '<a class="content-block2" href="/somewhere/else"></a>'},
        {"success": 1, "data": '<a class="content-block2" href="/comm-link/transmission/5-A"></a>'},
        "not a dict",
    ],
    ids=["empty", "failed", "failed-with-data", "no-data", "other-html", "other-link", "no-title", "not-dict"],
)
def test_changed_list_raises(body):
    from bot.feeds import FeedError, sc_commlink

    with pytest.raises(FeedError):
        sc_commlink.parse_rsi(body, NOW)


def wiki_item(item_id, **changes):
    from bot.feeds import sc_commlink

    row = json.loads(commlink_payload([item_id]))["data"][0]
    row.update(changes)
    return sc_commlink.parse({"data": [row]}, TZ)[0]


def rsi_item(item_id, **kwargs):
    from bot.feeds import sc_commlink

    return sc_commlink.parse_rsi(json.loads(rsi_payload(rsi_block(item_id, **kwargs))), NOW)[0]


def test_merge_combines_both_sources_without_duplicates():
    from bot.feeds import sc_commlink

    merged = sc_commlink.merge([wiki_item(1), wiki_item(2)], [rsi_item(2), rsi_item(3)])
    assert sorted(i.id for i in merged) == ["1", "2", "3"]


def test_merge_keeps_wiki_video_and_date_with_the_rsi_summary():
    from bot.feeds import sc_commlink

    wiki = wiki_item(2, links=[{"href": "https://www.youtube.com/watch?v=zNL_FgoTrjA"}])
    merged = sc_commlink.merge([wiki], [rsi_item(2, body="Official summary.")])[0]
    assert merged.description == "Official summary."
    assert merged.video == "https://www.youtube.com/watch?v=zNL_FgoTrjA"
    assert merged.timestamp == wiki.timestamp


def test_merge_keeps_the_wiki_summary_when_rsi_has_none():
    from bot.feeds import sc_commlink

    wiki = wiki_item(2, translations={"en_EN": "Wiki summary."})
    assert sc_commlink.merge([wiki], [rsi_item(2, body="")])[0].description == "Wiki summary."


def test_fetch_posts_the_expected_request(server):
    from bot.feeds import sc_commlink

    server.route("/w", (200, {}, commlink_payload([1])))
    server.route("/r", (200, {}, rsi_payload(rsi_block(2))))
    items = sc_commlink.fetch(server.base + "/w", TZ, rsi_url=server.base + "/r", now=NOW)
    assert sorted(i.id for i in items) == ["1", "2"]
    assert json.loads(server.posts("/r")[0]["body"])["sort"] == "publish_new"


def test_fetch_survives_rsi_failing_and_warns(server, monkeypatch):
    from bot.feeds import sc_commlink

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/w", (200, {}, commlink_payload([1])))
    server.route("/r", (500, {}, b"down"))
    warnings = []
    items = sc_commlink.fetch(server.base + "/w", TZ, rsi_url=server.base + "/r", now=NOW, warn=warnings.append)
    assert [i.id for i in items] == ["1"]
    assert len(warnings) == 1


def test_fetch_survives_wiki_failing_and_warns(server, monkeypatch):
    from bot.feeds import sc_commlink

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/w", (500, {}, b"down"))
    server.route("/r", (200, {}, rsi_payload(rsi_block(2))))
    warnings = []
    items = sc_commlink.fetch(server.base + "/w", TZ, rsi_url=server.base + "/r", now=NOW, warn=warnings.append)
    assert [i.id for i in items] == ["2"]
    assert len(warnings) == 1


def test_fetch_raises_when_both_fail(server, monkeypatch):
    from bot.feeds import FeedError, sc_commlink

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route("/w", (500, {}, b"down"))
    server.route("/r", (500, {}, b"down"))
    with pytest.raises(FeedError):
        sc_commlink.fetch(server.base + "/w", TZ, rsi_url=server.base + "/r", now=NOW)


def test_cover_falls_back_to_the_list_image(monkeypatch):
    from bot.feeds import sc_commlink

    monkeypatch.setattr(sc_commlink, "cover_image", lambda url: None)
    item = rsi_item(1)
    sc_commlink.add_covers([item])
    assert item.image == "https://media.example.test/channel_item_full.jpg"


def use_rsi(bot, server, *blocks):
    bot.config["sources"]["sc_commlink_rsi"] = server.base + "/rsi"
    server.route("/rsi", (200, {}, rsi_payload(*blocks)))


def test_article_only_on_rsi_is_announced_once(bot, server):
    use_rsi(bot, server, rsi_block(21431, title="Known"))
    bot.run()
    use_rsi(bot, server, rsi_block(21500, title="Brand new", body="Fresh summary."), rsi_block(21431, title="Known"))
    server.route("/article", (200, {}, b"<html></html>"))
    result = bot.run()
    assert result.returncode == 0, result.stderr
    posts = server.posts()
    assert len(posts) == 1
    embed = json.loads(posts[0]["body"])["embeds"][0]
    assert embed["title"] == "Brand new"
    assert embed["description"] == "Fresh summary."
    assert embed["footer"] == {"text": "Transmission"}
    assert "21500" in bot.state()["feeds"]["sc_commlink"]["seen"]
    bot.run()
    assert len(server.posts()) == 1


def test_article_is_not_repeated_when_the_wiki_catches_up(bot, server):
    use_rsi(bot, server, rsi_block(100))
    server.route("/commlink", (200, {}, commlink_payload([100])))
    bot.run()
    use_rsi(bot, server, rsi_block(101), rsi_block(100))
    bot.run()
    assert len(server.posts()) == 1
    server.route("/commlink", (200, {}, commlink_payload([101, 100])))
    bot.run()
    assert len(server.posts()) == 1


def test_old_article_on_rsi_is_not_sent(bot, server):
    use_rsi(bot, server, rsi_block(100))
    bot.run()
    use_rsi(bot, server, rsi_block(100), rsi_block(50, age="3 weeks ago"))
    bot.run()
    assert server.posts() == []


def test_changed_rsi_page_warns_and_the_wiki_still_works(bot, server):
    bot.config["sources"]["sc_commlink_rsi"] = server.base + "/rsi"
    server.route("/rsi", (200, {}, b"<html>moved</html>"))
    server.route("/commlink", (200, {}, commlink_payload([100])))
    bot.run()
    server.route("/commlink", (200, {}, commlink_payload([101, 100])))
    result = bot.run()
    assert result.returncode == 0, result.stderr
    assert "::warning" in result.stdout
    assert len(server.posts()) == 1
    assert bot.state()["feeds"]["sc_commlink"]["failing_since"] is None
