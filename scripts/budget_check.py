import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
LEDGER_DB_ID = "d066c98b-aa9b-40f3-86a6-b237db75d021"
BUDGET_DB_ID = "d897f317-b86d-4ece-ad5a-956f42353105"
STATE_PATH = "data/budget-alert-state.json"
THRESHOLDS = [100, 90, 70]


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


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs("data", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    tz = ZoneInfo("Asia/Seoul")
    today = datetime.now(tz).date()
    month_key = today.strftime("%Y-%m")

    budgets = {}
    for row in query_all(BUDGET_DB_ID):
        p = row["properties"]
        cat = rich_text_plain(p.get("카테고리", {}).get("title", []))
        amt = p.get("월예산", {}).get("number")
        if cat and amt:
            budgets[cat] = amt

    if not budgets:
        print("No budgets configured yet.")
        return

    spent = {}
    total_spent = 0
    for row in query_all(LEDGER_DB_ID):
        p = row["properties"]
        date_info = p.get("날짜", {}).get("date")
        if not date_info or not date_info.get("start"):
            continue
        if not date_info["start"].startswith(month_key):
            continue
        cat = p.get("카테고리", {}).get("select")
        cat_name = cat["name"] if cat else None
        amt = p.get("금액", {}).get("number") or 0
        total_spent += amt
        if cat_name:
            spent[cat_name] = spent.get(cat_name, 0) + amt

    state = load_state()
    month_state = state.get(month_key, {})

    # "총예산" is a special category meaning the whole household's total monthly
    # budget across every category, not a real 가계부 카테고리 value.
    TOTAL_BUDGET_LABEL = "총예산"

    alerts = []
    for cat, budget in budgets.items():
        used = total_spent if cat == TOTAL_BUDGET_LABEL else spent.get(cat, 0)
        pct = (used / budget) * 100 if budget else 0
        notified = month_state.get(cat, 0)
        for threshold in THRESHOLDS:
            if pct >= threshold and notified < threshold:
                alerts.append((cat, used, budget, pct))
                month_state[cat] = threshold
                break

    state[month_key] = month_state
    save_state(state)

    if not alerts:
        print("No new threshold crossed.")
        return

    lines = [f"{cat}: {used:,.0f}/{budget:,.0f}원 ({pct:.0f}% 사용)" for cat, used, budget, pct in alerts]
    message = "\n".join(lines)
    push_ntfy("서연의 예산 알림 💰", message)


if __name__ == "__main__":
    main()
