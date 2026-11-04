"""T1/T2: embed rules and webhook behaviour against a local server."""
import json
from datetime import datetime, timezone

import pytest

WEBHOOK = "/api/webhooks/1/secret"


def make_item(n=1, kind="commlink", title=None, description="desc", image=None):
    from bot.feeds import Item

    return Item(
        id=str(n), feed="sc_commlink" if kind == "commlink" else "sc_status", kind=kind,
        title=title or f"Title {n}", url=f"https://example.test/{n}", description=description,
        timestamp=datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc), image=image,
    )


def embed_size(embed):
    return len(embed.get("title", "")) + len(embed.get("description", ""))


def test_embed_commlink_fields():
    from bot import discord

    embed = discord.build_embed(make_item(image="https://example.test/i.jpg"))
    assert embed["title"] == "Title 1"
    assert embed["url"] == "https://example.test/1"
    assert embed["description"] == "desc"
    assert embed["color"] == 0x1E90FF
    assert embed["timestamp"].startswith("2026-11-02T20:00:00")
    assert embed["image"] == {"url": "https://example.test/i.jpg"}


def test_embed_status_fields():
    from bot import discord

    embed = discord.build_embed(make_item(kind="status"))
    assert embed["color"] == 0xE53935
    assert "image" not in embed


def test_embed_truncates_title_and_description():
    from bot import discord

    embed = discord.build_embed(make_item(title="ท" * 300, description="ข" * 5000))
    assert len(embed["title"]) == 256
    assert len(embed["description"]) == 4096


def test_each_message_has_one_embed_up_to_threshold():
    from bot import discord

    messages = discord.build_messages([make_item(i) for i in range(5)], threshold=5)
    assert len(messages) == 5
    for payload, items in messages:
        assert len(payload["embeds"]) == 1
        assert len(items) == 1


def test_batch_above_threshold_is_one_message():
    from bot import discord

    batch = [make_item(i) for i in range(6)]
    messages = discord.build_messages(batch, threshold=5)
    assert len(messages) == 1
    payload, items = messages[0]
    assert len(payload["embeds"]) == 1
    assert len(items) == 6
    text = payload["embeds"][0]["description"]
    assert all(f"Title {i}" in text for i in range(6))


def test_batch_within_all_discord_limits():
    from bot import discord

    batch = [make_item(i, title="ท" * 250, description="ข" * 4000) for i in range(200)]
    payload, items = discord.build_messages(batch, threshold=5)[0]
    assert len(items) == 200  # every item is covered even when the text is cut
    assert len(payload["embeds"]) <= discord.MAX_EMBEDS == 10
    assert sum(embed_size(e) for e in payload["embeds"]) <= discord.MAX_TOTAL == 6000
    assert all(len(e["description"]) <= 4096 and len(e["title"]) <= 256 for e in payload["embeds"])
    assert "194" in payload["embeds"][0]["description"] or "อีก" in payload["embeds"][0]["description"]


def test_single_message_total_is_under_6000():
    from bot import discord

    item = make_item(title="ท" * 300, description="ข" * 5000)
    payload, _ = discord.build_messages([item], threshold=5)[0]
    assert sum(embed_size(e) for e in payload["embeds"]) <= 6000


def test_batch_with_status_item_uses_red():
    from bot import discord

    batch = [make_item(i) for i in range(5)] + [make_item(9, kind="status")]
    payload, _ = discord.build_messages(batch, threshold=5)[0]
    assert payload["embeds"][0]["color"] == 0xE53935


def test_role_mention_goes_in_content():
    from bot import discord

    payload, _ = discord.build_messages([make_item()], threshold=5, mention="<@&42>")[0]
    assert payload["content"] == "<@&42>"
    assert payload["allowed_mentions"] == {"parse": ["roles"]}


def test_no_mention_by_default():
    from bot import discord

    payload, _ = discord.build_messages([make_item()], threshold=5)[0]
    assert "content" not in payload
    assert payload["allowed_mentions"] == {"parse": []}


def test_send_posts_json(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(WEBHOOK, (204, {}, b""))
    discord.send(server.base + WEBHOOK, {"embeds": [{"title": "x"}]})
    assert json.loads(server.posts(WEBHOOK)[0]["body"]) == {"embeds": [{"title": "x"}]}


def test_send_waits_retry_after_on_429(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(
        WEBHOOK,
        (429, {"Content-Type": "application/json"}, json.dumps({"retry_after": 0.4}).encode()),
        (204, {}, b""),
    )
    discord.send(server.base + WEBHOOK, {"embeds": []})
    posts = server.posts(WEBHOOK)
    assert len(posts) == 2
    assert posts[1]["at"] - posts[0]["at"] >= 0.4


def test_send_uses_retry_after_header_when_body_has_none(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(WEBHOOK, (429, {"Retry-After": "1"}, b"limited"), (204, {}, b""))
    discord.send(server.base + WEBHOOK, {"embeds": []})
    posts = server.posts(WEBHOOK)
    assert posts[1]["at"] - posts[0]["at"] >= 1


def test_send_gives_up_after_repeated_429(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(WEBHOOK, (429, {}, json.dumps({"retry_after": 0}).encode()))
    with pytest.raises(discord.DiscordError):
        discord.send(server.base + WEBHOOK, {"embeds": []})
    assert 2 <= len(server.posts(WEBHOOK)) <= 10


def test_send_retries_500_twice(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(WEBHOOK, (500, {}, b"boom"))
    with pytest.raises(discord.DiscordError):
        discord.send(server.base + WEBHOOK, {"embeds": []})
    assert len(server.posts(WEBHOOK)) == 3


def test_send_error_never_contains_url(server, monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    server.route(WEBHOOK, (400, {}, b"bad"))
    with pytest.raises(discord.DiscordError) as err:
        discord.send(server.base + WEBHOOK, {"embeds": []})
    assert "secret" not in str(err.value)
    assert len(server.posts(WEBHOOK)) == 1


def test_send_error_on_refused_connection_has_no_url(monkeypatch):
    from bot import discord

    monkeypatch.setenv("BOT_RETRY_BACKOFF", "0")
    with pytest.raises(discord.DiscordError) as err:
        discord.send("http://127.0.0.1:1/api/webhooks/1/secret", {"embeds": []})
    assert "secret" not in str(err.value)
    assert "secret" not in repr(err.value.__cause__)


def test_redact_removes_webhook_urls(monkeypatch):
    from bot import feeds

    fake = "https://discord.com/api/" + "webhooks/999/abcDEF"
    assert "abcDEF" not in feeds.redact(f"failed: {fake} oops")
    monkeypatch.setenv("SC_WEBHOOK", "http://127.0.0.1:9/custom-token")
    assert "custom-token" not in feeds.redact("error at http://127.0.0.1:9/custom-token!")
