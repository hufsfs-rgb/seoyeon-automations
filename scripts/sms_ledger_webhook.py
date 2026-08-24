import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
SMS_TEXT = os.environ.get("SMS_TEXT", "")
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
LEDGER_DB_ID = "d066c98b-aa9b-40f3-86a6-b237db75d021"
STATE_PATH = "data/sms-processed-hashes.json"

# Samsung Card approval SMS format, e.g.:
# "삼성8778승인 심*현 21260원 일시불 08/23 21:18 쿠팡누적5401264원"
SMS_PATTERN = re.compile(
    r"삼성(?P<last4>\d{4})승인\s+(?P<name>\S+)\s+(?P<amount>[\d,]+)원\s+"
    r"(?P<payment>\S+)\s+(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>.+?)누적(?P<cumulative>[\d,]+)원"
)


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs("data", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def create_page(properties):
    call("POST", "/pages", {"parent": {"database_id": LEDGER_DB_ID}, "properties": properties})


def main():
    if not SMS_TEXT.strip():
        print("No SMS text provided.")
        return

    text_hash = hashlib.sha256(SMS_TEXT.encode("utf-8")).hexdigest()
    state = load_state()
    if text_hash in state:
        print("Already processed (duplicate webhook call), skipping.")
        return

    tz = ZoneInfo("Asia/Seoul")
    today_iso = datetime.now(tz).date().isoformat()

    m = SMS_PATTERN.search(SMS_TEXT)
    if not m:
        # Don't silently drop unrecognized messages - log a flagged row for manual review.
        create_page({
            "항목": {"title": [{"text": {"content": "문자 파싱 실패 - 확인 필요"}}]},
            "날짜": {"date": {"start": today_iso}},
            "카테고리": {"select": {"name": "기타"}},
            "메모": {"rich_text": [{"text": {"content": SMS_TEXT}}]},
        })
        state[text_hash] = {"parsed": False, "recorded_at": today_iso}
        save_state(state)
        print(f"Could not parse SMS format, logged raw text for review: {SMS_TEXT!r}")
        return

    amount = float(m.group("amount").replace(",", ""))
    merchant = m.group("merchant").strip()
    payment = m.group("payment")
    mm, dd = m.group("date").split("/")
    year = datetime.now(tz).year
    date_iso = f"{year}-{mm}-{dd}"

    memo = "\n".join([
        f"문자 자동입력 (카드끝{m.group('last4')}, {payment}) - 카테고리 확인 필요",
        SMS_TEXT,
    ])

    create_page({
        "항목": {"title": [{"text": {"content": merchant}}]},
        "날짜": {"date": {"start": date_iso}},
        "금액": {"number": amount},
        "카테고리": {"select": {"name": "기타"}},
        "결제수단": {"select": {"name": "카드"}},
        "출처": {"select": {"name": "카드명세서"}},
        "메모": {"rich_text": [{"text": {"content": memo}}]},
    })

    state[text_hash] = {"parsed": True, "merchant": merchant, "amount": amount, "date": date_iso}
    save_state(state)
    print(f"Recorded: {merchant} {amount:,.0f}원 on {date_iso}")


if __name__ == "__main__":
    main()
