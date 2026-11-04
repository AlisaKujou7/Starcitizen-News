"""Entry point: one round of fetching, comparing, announcing and saving state."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import yaml

from bot import discord, state
from bot.feeds import redact, sc_commlink, sc_status

FEEDS = {"sc_commlink": sc_commlink, "sc_status": sc_status}


def log(message):
    print(redact(message), flush=True)


def warn(message):
    print(f"::warning::{redact(message)}", flush=True)


def sort_key(item):
    moment = item.timestamp.timestamp() if item.timestamp else 0
    return (moment, int(item.id) if item.id.isdigit() else 0, item.id)


def show(tag, payload):
    log(f"{tag} {json.dumps(payload, ensure_ascii=False)}")


def current_time():
    fixed = os.environ.get("BOT_NOW")  # tests pin the clock, so fixtures never age out of the 14-day window
    return datetime.fromisoformat(fixed) if fixed else datetime.now(timezone.utc)


def add_covers(items):
    sc_commlink.add_covers([i for i in items if i.kind == "commlink" and not i.compact and not i.video])


def collect(config, data, dry_run):
    """Fetch every enabled feed. One feed failing never stops the others."""
    pending = {}
    tz = config["timezone"]
    for name, settings in config["feeds"].items():
        if not settings.get("enabled"):
            continue
        try:
            items = FEEDS[name].fetch(config["sources"][name], tz)
        except Exception as exc:
            warn(f"ฟีด {name} ใช้งานไม่ได้: {exc if str(exc) else type(exc).__name__}")
            state.record_failure(data, name, datetime.now(timezone.utc).isoformat())
            continue
        state.record_success(data, name)
        if not state.is_bootstrapped(data, name):
            if dry_run:
                latest = max(items, key=sort_key)
                add_covers([latest])
                show(f"[PREVIEW] {name}: รอบจริงจะบันทึก {len(items)} รายการโดยไม่ส่ง ตัวอย่าง:", discord.build_embed(latest))
            else:
                state.bootstrap(data, name, items)
                log(f"{name}: รอบแรก บันทึก {len(items)} รายการโดยไม่ส่ง")
            continue
        found = state.new_items(data, name, items, now=current_time())
        log(f"{name}: ของใหม่ {len(found)} รายการ")
        pending.setdefault(settings["webhook"], []).extend(found)
    return pending


def announce(config, data, pending, state_path, dry_run):
    for secret_name, items in pending.items():
        if not items:
            continue
        threshold = config.get("batch_threshold", 5)
        if len(items) <= threshold:  # a batched message shows no picture, so no page needs opening
            add_covers(items)
        messages = discord.build_messages(sorted(items, key=sort_key), threshold, config.get("role_mention") or "")
        if dry_run:
            for payload, _ in messages:
                show("[DRY-RUN]", payload)
            continue
        url = os.environ.get(secret_name)
        if not url:
            warn(f"ไม่พบ secret {secret_name} จึงยังไม่ส่ง {len(items)} รายการ")
            continue
        for payload, covered in messages:
            try:
                discord.send(url, payload)
            except discord.DiscordError as exc:
                if not covered:  # only a video link was lost; its card already went out and must not repeat
                    warn(f"ส่งลิงก์คลิปเข้า {secret_name} ไม่สำเร็จ: {exc}")
                    continue
                warn(f"ส่งเข้า {secret_name} ไม่สำเร็จ: {exc} จะลองใหม่รอบถัดไป")
                break
            for item in covered:
                state.mark_sent(data, item)
            state.save(state_path, data)  # saved after every send, so a crash cannot repeat what went out


def run(args):
    if args.keepalive_check:
        print("due" if state.keepalive_due(args.last_commit_epoch, time.time()) else "not-due")
        return 0
    with open(args.config, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    data = state.load(args.state)
    pending = collect(config, data, args.dry_run)
    if not args.dry_run:
        state.save(args.state, data)
    announce(config, data, pending, args.state, args.dry_run)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="แจ้งข่าว Star Citizen เข้า Discord")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--dry-run", action="store_true", help="พิมพ์ข้อความแทนการส่ง และไม่เขียน state")
    parser.add_argument("--keepalive-check", action="store_true")
    parser.add_argument("--last-commit-epoch", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        # No traceback: a traceback could carry a URL into the Actions log.
        print(f"::error::{redact(f'{type(exc).__name__}: {exc}')}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
