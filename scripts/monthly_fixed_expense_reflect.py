import calendar
import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
FIXED_DB_ID = "a0c2dc43-360b-41e5-ac63-206bf1a05c5d"
LEDGER_DB_ID = "d066c98b-aa9b-40f3-86a6-b237db75d021"

# 이 스크립트는 결제수단="계좌이체"이면서 결제일이 고정된(null이 아닌) "매월" 고정지출 항목만
# 대상으로 함 - 카드 결제 항목은 sms_ledger_webhook.py가 실제 카드 문자 수신 시 자동 기록하므로
# 여기서 또 만들면 중복됨. 결제일이 불규칙한 항목(학원비, 딸 용돈 등)도 결제일=None이라
# 자동으로 제외됨(대표님이 매번 직접 확인 후 반영하는 걸로 유지).


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push_ntfy(title, message):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set, skipping push:", title, message)
        return
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message}
    req = urllib.request.Request(
        "https://ntfy.sh",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()


def rich_text_plain(rt_list):
    return "".join(rt.get("plain_text", "") for rt in (rt_list or []))


def query_all(db_id, filter_body=None):
    results, body = [], (dict(filter_body) if filter_body else {})
    while True:
        resp = call("POST", f"/databases/{db_id}/query", body)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        body = dict(body)
        body["start_cursor"] = resp["next_cursor"]
    return results


def already_reflected_this_month(item_name, ym):
    """True if 가계부 already has a row with this exact 항목 name for this 연월
    (avoids creating a duplicate if the workflow re-runs, or if 대표님/서연 already
    entered it manually earlier that day)."""
    filter_body = {
        "filter": {
            "and": [
                {"property": "항목", "title": {"equals": item_name}},
                {"property": "연월", "select": {"equals": ym}},
            ]
        }
    }
    rows = query_all(LEDGER_DB_ID, filter_body)
    return len(rows) > 0


def create_ledger_row(item_name, category, amount, date_iso, ym, existing_memo):
    memo_lines = [
        "고정지출 자동반영 (매달 결제일에 예상 금액으로 선반영됨) - 실제 청구액이 다르면 이 행의 금액을 수정할 것, 새 행을 또 만들지 말 것",
    ]
    if existing_memo:
        memo_lines.append(existing_memo)
    call("POST", "/pages", {
        "parent": {"database_id": LEDGER_DB_ID},
        "properties": {
            "항목": {"title": [{"text": {"content": item_name}}]},
            "날짜": {"date": {"start": date_iso}},
            "금액": {"number": amount},
            "카테고리": {"select": {"name": category}},
            "결제수단": {"select": {"name": "계좌이체"}},
            "출처": {"select": {"name": "계좌이체(실제)"}},
            "연월": {"select": {"name": ym}},
            "메모": {"rich_text": [{"text": {"content": "\n".join(memo_lines)}}]},
        },
    })


def main():
    tz = ZoneInfo("Asia/Seoul")
    today = datetime.now(tz).date()
    ym = today.strftime("%Y-%m")

    rows = query_all(FIXED_DB_ID)
    reflected = []
    for row in rows:
        p = row["properties"]
        cycle = (p.get("주기", {}).get("select") or {}).get("name")
        if cycle != "매월":
            continue
        payment_method = (p.get("결제수단", {}).get("select") or {}).get("name")
        if payment_method != "계좌이체":
            continue
        pay_day = p.get("결제일", {}).get("number")
        if pay_day is None:
            continue
        pay_day = int(pay_day)
        last_day_of_month = calendar.monthrange(today.year, today.month)[1]
        is_due_today = (today.day == last_day_of_month) if pay_day == 31 else (pay_day == today.day)
        if not is_due_today:
            continue

        item_name = rich_text_plain(p.get("항목", {}).get("title", []))
        amount = p.get("금액", {}).get("number")
        category = (p.get("카테고리", {}).get("select") or {}).get("name")
        existing_memo = rich_text_plain(p.get("메모", {}).get("rich_text", []))
        if not item_name or amount is None:
            continue

        if already_reflected_this_month(item_name, ym):
            print(f"Skip (already in 가계부 for {ym}): {item_name}")
            continue

        # 가계부 카테고리 select에는 "가족"/"보험"/"헌금"/"주거" 같은 고정지출 세부
        # 카테고리 옵션이 없음 - "교육"만 예외적으로 그대로 쓰고, 나머지는 전부
        # 가계부의 공용 "고정지출" 카테고리로 매핑함.
        ledger_category = "교육" if category == "교육" else "고정지출"

        date_iso = today.isoformat()
        create_ledger_row(item_name, ledger_category, amount, date_iso, ym, existing_memo)
        push_ntfy(
            f"고정지출 반영: {item_name}",
            f"{amount:,.0f}원 예상 금액으로 가계부에 반영했어요. 실제 계좌 청구액이 다르면 알려주세요!",
        )
        reflected.append((item_name, amount))
        print(f"Reflected: {item_name} {amount:,.0f}원 on {date_iso}")

    if not reflected:
        print("No 계좌이체 fixed expenses due today.")


if __name__ == "__main__":
    main()
