import json
import os
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TMAP_APP_KEY = os.environ["TMAP_APP_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

TMAP_URL = "https://apis.openapi.sk.com/tmap/routes?version=1"
NTFY_URL = "https://ntfy.sh"


def load_checks():
    with open("data/travel-checks.json", encoding="utf-8") as f:
        return json.load(f)


def get_route_seconds(start, end):
    body = {
        "startX": str(start["lon"]),
        "startY": str(start["lat"]),
        "endX": str(end["lon"]),
        "endY": str(end["lat"]),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "0",
        "trafficInfo": "Y",
    }
    req = urllib.request.Request(
        TMAP_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "appKey": TMAP_APP_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if "totalTime" in props:
            return props["totalTime"]
    raise RuntimeError(f"totalTime not found in TMAP response: {data}")


def push_ntfy(title, message):
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message}
    req = urllib.request.Request(
        NTFY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))


def main():
    tz = ZoneInfo("Asia/Seoul")
    today = datetime.now(tz).date()
    checks = load_checks()

    now = datetime.now(tz)
    todays = []
    for c in checks:
        if c["date"] != today.isoformat():
            continue
        arrive_by = datetime.strptime(c["arrive_by_kst"], "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=tz
        )
        if arrive_by <= now:
            continue  # already past, skip (e.g. second run of the day for an earlier leg)
        todays.append(c)

    if not todays:
        print("No upcoming travel checks scheduled for today.")
        return

    for check in todays:
        seconds = get_route_seconds(check["start"], check["end"])
        minutes = round(seconds / 60)

        arrive_by = datetime.strptime(check["arrive_by_kst"], "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=tz
        )
        depart_by = arrive_by - timedelta(minutes=minutes)

        message = (
            f"{check['start']['name']} → {check['end']['name']}\n"
            f"실시간 기준 약 {minutes}분 소요 예상\n"
            f"{arrive_by.strftime('%H:%M')}까지 도착하려면 "
            f"{depart_by.strftime('%H:%M')}까지 출발하세요!\n"
            f"({check['label']})"
        )
        push_ntfy("서연의 실시간 교통 체크 🚗", message)


if __name__ == "__main__":
    main()
