"""T3: the bot as a real process, against a local server. AC numbers follow the requirement's acceptance list."""
import json

from conftest import CANARY, WEBHOOK_PATH, commlink_payload

LATEST_ID = "21431"
STATUS_ID = "https://status.robertsspaceindustries.com/issues/2026-10-21_rsi-platform-maintenance/"


def test_ac1_first_run_is_silent_and_writes_state(bot, server):
    result = bot.run()
    assert result.returncode == 0, result.stderr
    assert server.all_posts() == []
    state = bot.state()
    assert LATEST_ID in state["feeds"]["sc_commlink"]["seen"]
    assert STATUS_ID in state["feeds"]["sc_status"]["seen"]


def test_ac2_forgetting_one_id_gives_exactly_one_message(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    result = bot.run()
    assert result.returncode == 0, result.stderr
    posts = server.posts()
    assert len(posts) == 1
    embed = json.loads(posts[0]["body"])["embeds"][0]
    assert embed["title"] == "This Week in Star Citizen"
    assert embed["color"] == 0x1E90FF
    assert LATEST_ID in bot.state()["feeds"]["sc_commlink"]["seen"]


def test_ac3_immediate_rerun_sends_nothing_more(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    bot.run()
    assert len(server.posts()) == 1
    result = bot.run()
    assert result.returncode == 0
    assert len(server.posts()) == 1


def test_ac4_all_messages_use_sc_webhook(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    bot.forget("sc_status", STATUS_ID)
    bot.run()
    assert len(server.all_posts()) == 2
    assert all(p["path"] == WEBHOOK_PATH for p in server.all_posts())


def test_ac6_broken_feed_does_not_stop_the_other(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    bot.config["sources"]["sc_status"] = server.base + "/wrong-url"
    result = bot.run()
    assert result.returncode == 0
    assert len(server.posts()) == 1
    assert "sc_status" in result.stdout + result.stderr


def test_ac6_broken_first_feed_does_not_stop_the_second(bot, server):
    bot.run()
    bot.forget("sc_status", STATUS_ID)
    bot.config["sources"]["sc_commlink"] = "http://127.0.0.1:1/refused"
    result = bot.run()
    assert result.returncode == 0
    assert len(server.posts()) == 1
    assert "sc_commlink" in result.stdout + result.stderr


def assert_no_canary(result, bot):
    text = result.stdout + result.stderr
    assert CANARY not in text
    assert "/api/webhooks/" not in text
    if bot.state_path.exists():
        assert CANARY not in bot.state_path.read_text(encoding="utf-8")


def test_ac7_secret_absent_on_success(bot):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    assert_no_canary(bot.run(), bot)


def test_ac7_secret_absent_when_discord_rejects(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    server.route(WEBHOOK_PATH, (403, {}, b"forbidden"))
    assert_no_canary(bot.run(), bot)


def test_ac7_secret_absent_when_webhook_unreachable(bot):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    result = bot.run(webhook=f"http://127.0.0.1:1/api/webhooks/123/{CANARY}")
    assert_no_canary(result, bot)


def test_ac8_dry_run_prints_without_sending(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    before = bot.state_path.read_bytes()
    result = bot.run("--dry-run", webhook=None)
    assert result.returncode == 0, result.stderr
    assert "This Week in Star Citizen" in result.stdout
    assert server.all_posts() == []
    assert bot.state_path.read_bytes() == before


def test_ac8_dry_run_without_state_previews_and_writes_nothing(bot, server):
    result = bot.run("--dry-run", webhook=None)
    assert result.returncode == 0, result.stderr
    assert "[PREVIEW]" in result.stdout
    assert "This Week in Star Citizen" in result.stdout
    assert "RSI Platform Maintenance" in result.stdout
    assert server.all_posts() == []
    assert not bot.state_path.exists()


def test_fr02_each_enabled_feed_is_fetched(bot, server):
    bot.run()
    assert len(server.gets("/commlink")) == 1
    assert len(server.gets("/status")) == 1


def test_fr02_commlink_request_asks_for_images(bot, server):
    bot.run()
    assert "include=images" in server.gets("/commlink")[0]["full_path"]


def test_fr08_more_than_threshold_is_one_message(bot, server):
    server.route("/commlink", (200, {}, commlink_payload([100, 101])))
    bot.run()
    server.route("/commlink", (200, {}, commlink_payload(range(100, 108))))
    result = bot.run()
    assert result.returncode == 0, result.stderr
    posts = server.posts()
    assert len(posts) == 1
    assert len(json.loads(posts[0]["body"])["embeds"]) == 1
    assert {str(i) for i in range(100, 108)} <= set(bot.state()["feeds"]["sc_commlink"]["seen"])


def test_fr08_threshold_comes_from_config(bot, server):
    bot.config["batch_threshold"] = 1
    server.route("/commlink", (200, {}, commlink_payload([100])))
    bot.run()
    server.route("/commlink", (200, {}, commlink_payload([100, 101, 102])))
    bot.run()
    assert len(server.posts()) == 1


def test_messages_go_out_oldest_first(bot, server):
    server.route("/commlink", (200, {}, commlink_payload([100])))
    bot.run()
    server.route("/commlink", (200, {}, commlink_payload([102, 101, 100])))
    bot.run()
    titles = [json.loads(p["body"])["embeds"][0]["title"] for p in server.posts()]
    assert titles == ["Article 101", "Article 102"]


def test_fr09_state_bytes_unchanged_without_new_items(bot):
    bot.run()
    before = bot.state_path.read_bytes()
    bot.run()
    assert bot.state_path.read_bytes() == before


def test_fr11_disabled_feed_not_fetched(bot, server):
    bot.config["feeds"]["sc_status"]["enabled"] = False
    bot.run()
    assert server.gets("/status") == []
    assert len(server.gets("/commlink")) == 1
    assert "sc_status" not in bot.state()["feeds"]


def test_webhook_secret_name_comes_from_config(bot, server, monkeypatch):
    monkeypatch.setenv("OTHER_HOOK", server.base + "/api/webhooks/9/other")
    server.route("/api/webhooks/9/other", (204, {}, b""))
    bot.config["feeds"]["sc_commlink"]["webhook"] = "OTHER_HOOK"
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    bot.run()
    assert len(server.posts("/api/webhooks/9/other")) == 1
    assert server.posts() == []


def test_role_mention_from_config(bot, server):
    bot.config["role_mention"] = "<@&42>"
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    bot.run()
    assert json.loads(server.posts()[0]["body"])["content"] == "<@&42>"


def test_r1_feed_failing_first_round_bootstraps_silently_later(bot, server):
    server.route("/status", (500, {}, b"down"))
    result = bot.run()
    assert result.returncode == 0
    assert bot.state()["feeds"]["sc_status"]["seen"] == []
    from conftest import fixture_bytes

    server.route("/status", (200, {}, fixture_bytes("status.xml")))
    result = bot.run()
    assert result.returncode == 0
    assert server.all_posts() == []
    assert STATUS_ID in bot.state()["feeds"]["sc_status"]["seen"]


def test_r2_failed_send_is_not_marked_and_is_retried_next_round(bot, server):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    server.route(WEBHOOK_PATH, (500, {}, b"boom"))
    result = bot.run()
    assert result.returncode == 0
    assert LATEST_ID not in bot.state()["feeds"]["sc_commlink"]["seen"]
    server.route(WEBHOOK_PATH, (204, {}, b""))
    server.requests.clear()
    bot.run()
    assert len(server.posts()) == 1
    assert LATEST_ID in bot.state()["feeds"]["sc_commlink"]["seen"]


def test_r2_missing_secret_is_not_marked(bot):
    bot.run()
    bot.forget("sc_commlink", LATEST_ID)
    result = bot.run(webhook=None)
    assert result.returncode == 0
    assert "SC_WEBHOOK" in result.stdout + result.stderr
    assert LATEST_ID not in bot.state()["feeds"]["sc_commlink"]["seen"]


def test_r2_partial_batch_keeps_what_was_sent(bot, server):
    server.route("/commlink", (200, {}, commlink_payload([100])))
    bot.run()
    server.route("/commlink", (200, {}, commlink_payload([102, 101, 100])))
    server.route(WEBHOOK_PATH, (204, {}, b""), (400, {}, b"bad"))
    bot.run()
    seen = bot.state()["feeds"]["sc_commlink"]["seen"]
    assert "101" in seen
    assert "102" not in seen


def test_r3_empty_source_does_not_touch_state(bot, server):
    bot.run()
    before = bot.state()["feeds"]["sc_commlink"]["seen"]
    server.route("/commlink", (200, {}, json.dumps({"data": []}).encode()))
    result = bot.run()
    assert result.returncode == 0
    assert bot.state()["feeds"]["sc_commlink"]["seen"] == before
    assert server.all_posts() == []


def test_r3_changed_schema_does_not_touch_state(bot, server):
    bot.run()
    before = bot.state()["feeds"]["sc_status"]["seen"]
    server.route("/status", (200, {}, b"<html>we moved</html>"))
    result = bot.run()
    assert result.returncode == 0
    assert bot.state()["feeds"]["sc_status"]["seen"] == before
    assert server.all_posts() == []


def test_r8_corrupt_state_stops_with_error_and_sends_nothing(bot, server):
    bot.state_path.write_text("{broken", encoding="utf-8")
    result = bot.run()
    assert result.returncode != 0
    assert server.all_posts() == []
    assert bot.state_path.read_text(encoding="utf-8") == "{broken"


def test_d3_failure_is_visible_and_clears(bot, server):
    bot.run()
    server.route("/status", (500, {}, b"down"))
    result = bot.run()
    assert "::warning" in result.stdout
    since = bot.state()["feeds"]["sc_status"]["failing_since"]
    assert since
    before = bot.state_path.read_bytes()
    bot.run()
    assert bot.state_path.read_bytes() == before  # an ongoing outage must not create a commit every round
    assert server.all_posts() == []
    from conftest import fixture_bytes

    server.route("/status", (200, {}, fixture_bytes("status.xml")))
    bot.run()
    assert bot.state()["feeds"]["sc_status"]["failing_since"] is None


COVER = "https://cdn.example.test/cover.jpg"
COVER_PAGE = f'<html><head><meta property="og:image" content="{COVER}"></head></html>'.encode()


def articles(server, ids):
    """A comm-link body whose article pages live on the local server."""
    body = json.loads(commlink_payload(ids))
    for row in body["data"]:
        row["rsi_url"] = f"{server.base}/article/{row['id']}"
    return json.dumps(body).encode()


def start_with_one_new_article(bot, server):
    server.route("/commlink", (200, {}, articles(server, [100])))
    bot.run()
    server.route("/commlink", (200, {}, articles(server, [101, 100])))


def test_fr13_message_uses_the_cover_from_the_article_page(bot, server):
    start_with_one_new_article(bot, server)
    server.route("/article/101", (200, {}, COVER_PAGE))
    result = bot.run()
    assert result.returncode == 0, result.stderr
    assert json.loads(server.posts()[0]["body"])["embeds"][0]["image"] == {"url": COVER}


def test_fr13_failed_cover_still_sends_and_marks(bot, server):
    start_with_one_new_article(bot, server)
    server.route("/article/101", (500, {}, b"boom"))
    result = bot.run()
    assert result.returncode == 0, result.stderr
    embed = json.loads(server.posts()[0]["body"])["embeds"][0]
    assert embed["title"] == "Article 101"
    assert "image" not in embed
    assert "101" in bot.state()["feeds"]["sc_commlink"]["seen"]


def test_fr13_first_round_opens_no_article_page(bot, server):
    server.route("/commlink", (200, {}, articles(server, [100, 101])))
    bot.run()
    assert server.gets("/article/100") == []
    assert server.gets("/article/101") == []


def test_fr13_batch_opens_no_article_page(bot, server):
    server.route("/commlink", (200, {}, articles(server, [100])))
    bot.run()
    server.route("/commlink", (200, {}, articles(server, range(100, 108))))
    bot.run()
    assert len(server.posts()) == 1
    assert server.gets("/article/101") == []


def test_fr13_known_article_page_is_not_reopened(bot, server):
    start_with_one_new_article(bot, server)
    server.route("/article/101", (200, {}, COVER_PAGE))
    bot.run()
    bot.run()
    assert len(server.gets("/article/101")) == 1


def test_fr13_status_items_have_no_cover(bot, server):
    bot.run()
    rss = (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>RSI Status</title>'
        f"<item><title>[Resolved] Outage</title><link>{server.base}/article/status</link>"
        "<pubDate>Wed, 04 Nov 2026 00:00:00 +0000</pubDate><guid>new-incident</guid></item></channel></rss>"
    )
    server.route("/status", (200, {}, rss.encode()))
    server.route("/article/status", (200, {}, COVER_PAGE))
    bot.run()
    assert server.gets("/article/status") == []
    assert "image" not in json.loads(server.posts()[0]["body"])["embeds"][0]


def test_fr13_dry_run_shows_the_cover(bot, server):
    start_with_one_new_article(bot, server)
    server.route("/article/101", (200, {}, COVER_PAGE))
    result = bot.run("--dry-run", webhook=None)
    assert COVER in result.stdout
    assert server.all_posts() == []


def test_d2_keepalive_check_command(bot):
    assert bot.run("--keepalive-check", "--last-commit-epoch", "0").stdout.strip() == "due"
    import time

    recent = str(int(time.time()) - 3600)
    assert bot.run("--keepalive-check", "--last-commit-epoch", recent).stdout.strip() == "not-due"
