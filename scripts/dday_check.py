import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo
import urllib.request

THRESHOLDS = {7, 3, 1, 0}

def load_events():
    with open("data/important-events.json", encoding="utf-8") as f:
        return json.load(f)

def main():
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    events = load_events()

    hits = []
    for ev in events:
        ev_date = date.fromisoformat(ev["date"])
        days_left = (ev_date - today).days
        if days_left in THRESHOLDS:
            hits.append((days_left, ev["name"]))

    if not hits:
        print("No D-day matches today.")
        return

    hits.sort(key=lambda x: x[0])
    lines = []
    for days_left, name in hits:
        if days_left == 0:
            lines.append(f"오늘! {name}")
        else:
            lines.append(f"D-{days_left} {name}")

    message = "\n".join(lines)
    title = "서연의 D-day 알림 📌"

    payload = {
        "topic": os.environ["NTFY_TOPIC"],
        "title": title,
        "message": message,
    }
    req = urllib.request.Request(
        "https://ntfy.sh",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))

if __name__ == "__main__":
    main()
