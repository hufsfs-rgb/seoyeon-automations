import json
import os
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
FIXED_DB_ID = "a0c2dc43-360b-41e5-ac63-206bf1a05c5d"


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rich_text_plain(rt_list):
    return "".join(rt.get("plain_text", "") for rt in (rt_list or []))


def query_all(db_id):
    results, body = [], {}
    while True:
        resp = call("POST", f"/databases/{db_id}/query", body)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        body = {"start_cursor": resp["next_cursor"]}
    return results


def push_ntfy(title, message):
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message}
    req = urllib.request.Request(
        "https://ntfy.sh",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))


def main():
    tz = ZoneInfo("Asia/Seoul")
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    rows = query_all(FIXED_DB_ID)

    due = []
    for row in rows:
        p = row["properties"]
        active = p.get("활성", {}).get("checkbox", False)
        if not active:
            continue
        pay_day = p.get("결제일", {}).get("number")
        if pay_day is None:
            continue
        if int(pay_day) != tomorrow.day:
            continue
        cycle = (p.get("주기", {}).get("select") or {}).get("name", "매월")
        if cycle == "매년":
            pay_month = p.get("결제월", {}).get("number")
            if pay_month is None or int(pay_month) != tomorrow.month:
                continue
        name = rich_text_plain(p.get("항목", {}).get("title", []))
        amount = p.get("금액", {}).get("number")
        due.append((name, amount))

    if not due:
        print("No fixed expenses due tomorrow.")
        return

    lines = [f"- {name} {amount:,.0f}원" if amount else f"- {name}" for name, amount in due]
    message = "내일 결제 예정:\n" + "\n".join(lines)
    push_ntfy("서연의 고정지출 알림 💳", message)


if __name__ == "__main__":
    main()
