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

# Domestic (원화) card approval SMS format - shared by Samsung and Hana, e.g.:
# "삼성8778승인 심*현 21260원 일시불 08/23 21:18 쿠팡누적5401264원"
# "[Web발신]\n하나9*6*승인 심*현 8,600원 일시불 08/06 09:52 구글페이먼트코리아유 누적554,218원"
DOMESTIC_PATTERN = re.compile(
    r"(?P<issuer>삼성|하나)(?P<mask>[\d*]+)승인\s+(?P<name>\S+)\s+(?P<amount>[\d,]+)원\s+"
    r"(?P<payment>\S+)\s+(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>.+?)누적(?P<cumulative>[\d,]+)원"
)
ISSUER_LABELS = {"삼성": "삼성카드", "하나": "하나카드"}

# Hana Card overseas approval SMS format, e.g.:
# "[Web발신]\n하나9*6*해외승인 심*현 USD22.00 08/22 15:19 ANTHROPIC* CLAUDE SU"
# No KRW amount is given (foreign currency + date/time + merchant only, no 누적 field).
HANA_OVERSEAS_PATTERN = re.compile(
    r"하나(?P<mask>[\d*]+)해외승인\s+(?P<name>\S+)\s+"
    r"(?P<currency>[A-Z]{3})(?P<amount>[\d,.]+)\s+"
    r"(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+(?P<merchant>.+)"
)


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_krw_rate(date_iso, currency):
    """Return KRW per 1 unit of currency on date_iso (ECB reference rate via
    Frankfurter), or None if the lookup fails. Falls back to the nearest earlier
    published rate automatically for weekends/holidays."""
    url = f"https://api.frankfurter.dev/v1/{date_iso}?base={currency}&symbols=KRW"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["rates"]["KRW"]
    except Exception as e:
        print(f"Exchange rate lookup failed for {currency} on {date_iso}: {e}")
        return None


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
    year = datetime.now(tz).year

    m = DOMESTIC_PATTERN.search(SMS_TEXT)
    if m:
        issuer_label = ISSUER_LABELS.get(m.group("issuer"), m.group("issuer"))
        amount = float(m.group("amount").replace(",", ""))
        merchant = m.group("merchant").strip()
        payment = m.group("payment")
        mm, dd = m.group("date").split("/")
        date_iso = f"{year}-{mm}-{dd}"
        memo = "\n".join([
            f"문자 자동입력 ({issuer_label} 끝{m.group('mask')}, {payment}) - 카테고리 확인 필요",
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
        state[text_hash] = {"parsed": True, "card": m.group("issuer"), "merchant": merchant, "amount": amount, "date": date_iso}
        save_state(state)
        print(f"Recorded ({issuer_label}): {merchant} {amount:,.0f}원 on {date_iso}")
        return

    m = HANA_OVERSEAS_PATTERN.search(SMS_TEXT)
    if m:
        merchant = m.group("merchant").strip()
        currency = m.group("currency")
        fx_amount = float(m.group("amount").replace(",", ""))
        mm, dd = m.group("date").split("/")
        date_iso = f"{year}-{mm}-{dd}"

        # Prioritize completeness over precision: apply that day's published rate
        # automatically (approximate - doesn't include the card issuer's actual FX
        # fee/spread) rather than leaving the amount blank pending manual entry.
        rate = fetch_krw_rate(date_iso, currency)
        if rate is not None:
            krw_amount = round(fx_amount * rate)
            title = merchant
            memo = "\n".join([
                f"하나카드 해외결제 - {currency}{fx_amount:,.2f} → 자동 환율({date_iso} ECB 기준 1{currency}={rate:,.2f}원) 적용 "
                "- 카드사 실제 청구액(수수료 포함)과 다를 수 있음, 카테고리 확인 필요",
                SMS_TEXT,
            ])
            properties = {
                "항목": {"title": [{"text": {"content": title}}]},
                "날짜": {"date": {"start": date_iso}},
                "금액": {"number": krw_amount},
                "카테고리": {"select": {"name": "기타"}},
                "결제수단": {"select": {"name": "카드"}},
                "출처": {"select": {"name": "카드명세서"}},
                "메모": {"rich_text": [{"text": {"content": memo}}]},
            }
        else:
            # Rate lookup failed - still record the transaction (don't drop it),
            # just without a KRW amount, flagged for manual entry.
            title = f"[해외/환산필요] {merchant}"
            memo = "\n".join([
                f"하나카드 해외결제 - {currency}{fx_amount:,.2f} (환율 자동조회 실패, 원화 금액 직접 입력 필요)",
                SMS_TEXT,
            ])
            properties = {
                "항목": {"title": [{"text": {"content": title}}]},
                "날짜": {"date": {"start": date_iso}},
                "카테고리": {"select": {"name": "기타"}},
                "결제수단": {"select": {"name": "카드"}},
                "출처": {"select": {"name": "카드명세서"}},
                "메모": {"rich_text": [{"text": {"content": memo}}]},
            }

        create_page(properties)
        state[text_hash] = {
            "parsed": True,
            "card": "hana_overseas",
            "merchant": merchant,
            "fx": f"{currency}{fx_amount}",
            "krw_amount": krw_amount if rate is not None else None,
            "date": date_iso,
        }
        save_state(state)
        if rate is not None:
            print(f"Recorded (Hana overseas): {merchant} {currency}{fx_amount:,.2f} -> {krw_amount:,.0f}원 on {date_iso}")
        else:
            print(f"Recorded (Hana overseas, rate lookup failed): {merchant} {currency}{fx_amount:,.2f} on {date_iso}")
        return

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


if __name__ == "__main__":
    main()
