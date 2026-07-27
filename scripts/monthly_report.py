import json
import os
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
LEDGER_DB_ID = "d066c98b-aa9b-40f3-86a6-b237db75d021"


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_all(db_id):
    results, body = [], {}
    while True:
        resp = call("POST", f"/databases/{db_id}/query", body)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        body = {"start_cursor": resp["next_cursor"]}
    return results


def main():
    tz = ZoneInfo("Asia/Seoul")
    today = datetime.now(tz).date()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    month_key = last_month_end.strftime("%Y-%m")

    totals = {}
    grand_total = 0
    for row in query_all(LEDGER_DB_ID):
        p = row["properties"]
        date_info = p.get("날짜", {}).get("date")
        if not date_info or not date_info.get("start"):
            continue
        if not date_info["start"].startswith(month_key):
            continue
        cat = p.get("카테고리", {}).get("select")
        cat_name = cat["name"] if cat else "미분류"
        amt = p.get("금액", {}).get("number") or 0
        totals[cat_name] = totals.get(cat_name, 0) + amt
        grand_total += amt

    if grand_total == 0:
        print(f"No expenses recorded for {month_key}.")
        return

    lines = [f"{month_key} 총지출: {grand_total:,.0f}원"] + [
        f"- {cat}: {amt:,.0f}원 ({amt / grand_total * 100:.0f}%)"
        for cat, amt in sorted(totals.items(), key=lambda x: -x[1])
    ]
    memo = "\n".join(lines)

    body = {
        "parent": {"database_id": LEDGER_DB_ID},
        "properties": {
            "항목": {"title": [{"text": {"content": f"📊 {month_key} 월간 리포트"}}]},
            "날짜": {"date": {"start": last_month_end.isoformat()}},
            "금액": {"number": grand_total},
            "메모": {"rich_text": [{"text": {"content": memo}}]},
        },
    }
    call("POST", "/pages", body)
    print(f"Monthly report created for {month_key}: {grand_total:,.0f}원")


if __name__ == "__main__":
    main()
