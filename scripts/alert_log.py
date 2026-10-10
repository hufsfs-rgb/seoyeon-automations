"""Record every ntfy push in the Notion "알림 로그" DB so the nightly diary
and weekly retro routines know what 대표님 was notified about.

Best-effort: logging must never break the push itself, so all errors are
swallowed and printed.

CLI (for workflows that push with curl):
    python scripts/alert_log.py <출처> <제목> <내용>
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ALERT_LOG_DB_ID = "6577ac0b-5c32-44eb-b5e0-227a14cdafe8"


def log_alert(source, title, message):
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("alert_log: NOTION_TOKEN missing, skipped")
        return
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    body = {
        "parent": {"database_id": ALERT_LOG_DB_ID},
        "properties": {
            "제목": {"title": [{"text": {"content": (title or "(제목 없음)")[:200]}}]},
            "시각": {"date": {"start": now.isoformat(timespec="seconds")}},
            "출처": {"select": {"name": source}},
            "내용": {"rich_text": [{"text": {"content": (message or "")[:1900]}}]},
            "날짜": {"rich_text": [{"text": {"content": now.strftime("%Y-%m-%d")}}]},
        },
    }
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
        print(f"alert_log: logged [{source}] {title}")
    except Exception as e:
        print(f"alert_log: failed ({e})")


if __name__ == "__main__":
    log_alert(*(sys.argv[1:4] + [""] * (3 - len(sys.argv[1:4]))))
