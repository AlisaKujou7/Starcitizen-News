"""T1: the workflow and config files, read as data. Whether GitHub really runs them is checked in T6."""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def notify():
    return yaml.safe_load((REPO / ".github/workflows/notify.yml").read_text(encoding="utf-8"))


def notify_text():
    return (REPO / ".github/workflows/notify.yml").read_text(encoding="utf-8")


def config():
    return yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))


def triggers():
    wf = notify()
    return wf.get("on", wf.get(True))  # YAML reads a bare `on` key as True


def test_schedule_and_manual_trigger():
    on = triggers()
    assert "workflow_dispatch" in on
    minutes = on["schedule"][0]["cron"].split()[0]
    values = [int(m) for m in minutes.split(",")]
    assert len(values) == 2 and values[1] - values[0] == config()["schedule_minutes"] == 30


def test_permissions_and_secret_handling():
    assert notify()["permissions"] == {"contents": "write"}
    text = notify_text()
    assert "${{ secrets.SC_WEBHOOK }}" in text
    assert "discord.com" not in text
    assert "echo" not in "".join(line for line in text.splitlines() if "SC_WEBHOOK" in line)


def test_no_overlapping_runs_and_time_limit():
    wf = notify()
    assert wf["concurrency"]["cancel-in-progress"] is False
    job = next(iter(wf["jobs"].values()))
    assert job["timeout-minutes"] <= 5


def test_commit_only_when_changed_and_push_failure_is_red():
    text = notify_text()
    assert "git diff --cached --quiet" in text
    assert "git add state.json" in text
    assert "git pull --rebase" in text
    assert "git push" in text
    assert "|| true" not in text
    assert "continue-on-error" not in text


def test_state_is_committed_even_if_the_bot_step_failed():
    job = next(iter(notify()["jobs"].values()))
    commit_step = next(s for s in job["steps"] if "git push" in s.get("run", ""))
    assert "cancelled()" in commit_step["if"]


def test_keepalive_step():
    text = notify_text()
    assert "--keepalive-check" in text
    assert "--allow-empty" in text


def test_python_312_and_min_deps():
    job = next(iter(notify()["jobs"].values()))
    setup = next(s for s in job["steps"] if "setup-python" in s.get("uses", ""))
    assert str(setup["with"]["python-version"]) == "3.12"
    names = [
        re.split(r"[=<>!~]", line.strip())[0].lower()
        for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(names) == ["feedparser", "pyyaml", "requests"]


def test_config_matches_requirement():
    cfg = config()
    assert cfg["timezone"] == "Asia/Bangkok"
    assert cfg["batch_threshold"] == 5
    assert cfg["role_mention"] == "<@&1567446930320138280>"
    assert set(cfg["feeds"]) == {"sc_commlink", "sc_status"}
    assert all(f["enabled"] is True and f["webhook"] == "SC_WEBHOOK" for f in cfg["feeds"].values())
    assert cfg["sources"]["sc_commlink"] == "https://api.star-citizen.wiki/api/comm-links"
    assert cfg["sources"]["sc_status"] == "https://status.robertsspaceindustries.com/index.xml"
    assert cfg["sources"]["sc_commlink_rsi"] == "https://robertsspaceindustries.com/api/hub/getCommlinkItems"


def test_tests_workflow_runs_offline_suite():
    wf = yaml.safe_load((REPO / ".github/workflows/test.yml").read_text(encoding="utf-8"))
    text = str(wf)
    assert "pytest" in text
    assert "not live" in text


def test_real_state_file_is_not_preseeded_with_secrets():
    path = REPO / "state.json"
    if path.exists():
        assert "webhooks" not in path.read_text(encoding="utf-8")
