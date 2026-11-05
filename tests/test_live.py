"""T4: read-only checks against the real sources. Nothing here can reach Discord: no webhook is ever set."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live


def cfg():
    return yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))


def test_live_commlink_parses():
    from bot import discord
    from bot.feeds import sc_commlink

    items = sc_commlink.fetch(cfg()["sources"]["sc_commlink"], "Asia/Bangkok")
    assert len(items) >= 5
    assert all(i.id.isdigit() and i.title and i.url.startswith("https://") for i in items)
    assert discord.build_embed(items[0])["title"]


def test_live_article_page_has_a_cover():
    from bot.feeds import sc_commlink

    items = sc_commlink.fetch(cfg()["sources"]["sc_commlink"], "Asia/Bangkok")
    articles = [i for i in items if not i.title.startswith("R-PU-")]
    cover = sc_commlink.cover_image(articles[0].url)
    assert cover and cover.startswith("https://")


def test_live_rsi_list_parses():
    from datetime import datetime, timezone

    from bot.feeds import sc_commlink

    wiki = cfg()["sources"]["sc_commlink"]
    rsi = cfg()["sources"]["sc_commlink_rsi"]
    warnings = []
    items = sc_commlink.fetch(wiki, "Asia/Bangkok", rsi_url=rsi, now=datetime.now(timezone.utc), warn=warnings.append)
    assert warnings == []
    assert len(items) >= 5
    assert all(i.id.isdigit() and i.title and i.url.startswith("https://") for i in items)


def test_live_api_still_returns_links():
    import requests

    from bot.feeds import sc_commlink

    response = requests.get(
        cfg()["sources"]["sc_commlink"], params=sc_commlink.QUERY, headers={"Accept": "application/json"}, timeout=30
    )
    assert isinstance(response.json()["data"][0]["links"], list)


def test_live_latest_article_has_a_summary():
    from bot.feeds import sc_commlink

    items = sc_commlink.fetch(cfg()["sources"]["sc_commlink"], "Asia/Bangkok")
    articles = [i for i in items if not i.title.startswith("R-PU-")]
    assert articles[0].description
    assert len(articles[0].description) <= 300


def test_live_status_parses():
    from bot import discord
    from bot.feeds import sc_status

    items = sc_status.fetch(cfg()["sources"]["sc_status"], "Asia/Bangkok")
    assert len(items) >= 5
    assert all(i.id and i.title and i.timestamp for i in items)
    assert discord.build_embed(items[0])["color"] == 0xE53935


def test_live_dry_run_under_two_minutes(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "SC_WEBHOOK"}
    state = tmp_path / "state.json"
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "bot.main", "--dry-run", "--config", "config.yaml", "--state", str(state)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=130,
    )
    assert time.monotonic() - started < 120
    assert result.returncode == 0, result.stderr
    assert "::warning" not in result.stdout
    assert result.stdout.count("[PREVIEW]") == 2
    assert not state.exists()
