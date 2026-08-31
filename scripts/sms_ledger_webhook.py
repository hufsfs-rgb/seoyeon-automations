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

# Domestic (원화) card approval SMS format - shared by Samsung and Hana. The real
# SMS can be single-line (spaces) or multi-line (\r\n between fields) - \s+ handles
# both, but the merchant->누적 boundary needs \s* too since a line break can sit
# right before "누적" with no space, e.g.:
# "삼성8778승인 심*현 21260원 일시불 08/23 21:18 쿠팡누적5401264원"
# "[Web발신]\n하나9*6*승인 심*현 8,600원 일시불 08/06 09:52 구글페이먼트코리아유 누적554,218원"
# "[Web발신]\n삼성8778승인 심*현\r\n33,000원 일시불\r\n08/24 20:31 별온누리약국\r\n누적5,434,264원"
DOMESTIC_PATTERN = re.compile(
    r"(?P<issuer>삼성|하나)(?P<mask>[\d*]+)승인\s+(?P<name>\S+)\s+(?P<amount>[\d,]+)원\s+"
    r"(?P<payment>\S+)\s+(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>[^\n]+?)\s*누적(?P<cumulative>[\d,]+)원"
)
ISSUER_LABELS = {"삼성": "삼성카드", "하나": "하나카드"}

# Cancellation SMS - same shape as DOMESTIC_PATTERN but "취소" instead of "승인",
# and a "-" before the amount, e.g.:
# "[Web발신]\n삼성8778취소 심*현\r\n-54,350원 일시불\r\n08/25 20:54 쿠팡\r\n누적5,452,944원"
CANCEL_PATTERN = re.compile(
    r"(?P<issuer>삼성|하나)(?P<mask>[\d*]+)취소\s+(?P<name>\S+)\s+-?(?P<amount>[\d,]+)원\s+"
    r"(?P<payment>\S+)\s+(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>[^\n]+?)\s*누적(?P<cumulative>[\d,]+)원"
)

# Lotte Card domestic approval SMS format (multi-line, different field order), e.g.:
# "[Web발신]\n이스타항공 주\n1,329,900원 승인\n심*현 롯데8*7*\n일시불 08/19 13:14\n누적1,375,750원"
LOTTE_PATTERN = re.compile(
    r"(?P<merchant>[^\n]+?)\s*\n\s*(?P<amount>[\d,]+)원\s*승인\s*\n\s*"
    r"(?P<name>\S+)\s+롯데(?P<mask>[\d*]+)\s*\n\s*"
    r"(?P<payment>\S+)\s+(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s*\n\s*"
    r"누적(?P<cumulative>[\d,]+)원"
)

# Recurring auto-payment ("자동결제") SMS - different shape entirely, no name/누적
# field, issuer is bracketed with the word 카드 already included, e.g.:
# "[Web발신]\n[삼성카드]8778\n자동결제 08/25접수\n아파트관리비\n397,780원"
AUTOPAY_PATTERN = re.compile(
    r"\[(?P<issuer>[^\]]+)\](?P<mask>[\d*]+)\s*\n\s*"
    r"자동결제\s*(?P<date>\d{2}/\d{2})\s*접수\s*\n\s*"
    r"(?P<merchant>[^\n]+?)\s*\n\s*"
    r"(?P<amount>[\d,]+)원"
)

# Hana Card overseas approval SMS format, e.g.:
# "[Web발신]\n하나9*6*해외승인 심*현 USD22.00 08/22 15:19 ANTHROPIC* CLAUDE SU"
# No KRW amount is given (foreign currency + date/time + merchant only, no 누적 field).
HANA_OVERSEAS_PATTERN = re.compile(
    r"하나(?P<mask>[\d*]+)해외승인\s+(?P<name>\S+)\s+"
    r"(?P<currency>[A-Z]{3})(?P<amount>[\d,.]+)\s+"
    r"(?P<date>\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2})\s+(?P<merchant>.+)"
)


# Known merchant name -> (category, memo note) overrides, confirmed by 대표님.
# Anything not listed here defaults to 기타 + "카테고리 확인 필요" as before.
# EXACT_MERCHANT_OVERRIDES matches only when the merchant text equals the key
# exactly - use this when a substring match would wrongly catch other merchants
# (e.g. "쿠팡" alone must not also match "쿠팡이츠" delivery orders).
EXACT_MERCHANT_OVERRIDES = {
    "쿠팡": ("생활", "쿠팡 마켓 구매"),
}
MERCHANT_CATEGORY_OVERRIDES = {
    "에이치에스홀딩스": ("교통", "광명역 주차장 사용요금"),
    "IHERB": ("생활", "iHerb 해외직구"),
    "스시로": ("식비", "스시로(일식 체인)"),
    "이마트": ("식비", "이마트/이마트에브리데이 등 마트 체인, 장보기"),
}


def resolve_category(merchant):
    merchant_stripped = merchant.strip()
    if merchant_stripped in EXACT_MERCHANT_OVERRIDES:
        return EXACT_MERCHANT_OVERRIDES[merchant_stripped]
    for key, (category, note) in MERCHANT_CATEGORY_OVERRIDES.items():
        if key in merchant:
            return category, note
    return "기타", "카테고리 확인 필요"


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
        category, note = resolve_category(merchant)
        memo = "\n".join([
            f"문자 자동입력 ({issuer_label} 끝{m.group('mask')}, {payment}) - {note}",
            SMS_TEXT,
        ])
        create_page({
            "항목": {"title": [{"text": {"content": merchant}}]},
            "날짜": {"date": {"start": date_iso}},
            "금액": {"number": amount},
            "카테고리": {"select": {"name": category}},
            "결제수단": {"select": {"name": "카드"}},
            "출처": {"select": {"name": "카드명세서"}},
            "메모": {"rich_text": [{"text": {"content": memo}}]},
        })
        state[text_hash] = {"parsed": True, "card": m.group("issuer"), "merchant": merchant, "amount": amount, "date": date_iso}
        save_state(state)
        print(f"Recorded ({issuer_label}): {merchant} {amount:,.0f}원 on {date_iso}")
        return

    m = CANCEL_PATTERN.search(SMS_TEXT)
    if m:
        issuer_label = ISSUER_LABELS.get(m.group("issuer"), m.group("issuer"))
        amount = float(m.group("amount").replace(",", ""))
        merchant = m.group("merchant").strip()
        mm, dd = m.group("date").split("/")
        date_iso = f"{year}-{mm}-{dd}"
        memo = "\n".join([
            f"결제 취소 - 이전 승인 건 상쇄용 마이너스 기록 ({issuer_label} 끝{m.group('mask')})",
            SMS_TEXT,
        ])
        create_page({
            "항목": {"title": [{"text": {"content": f"[취소] {merchant}"}}]},
            "날짜": {"date": {"start": date_iso}},
            "금액": {"number": -amount},
            "카테고리": {"select": {"name": "기타"}},
            "결제수단": {"select": {"name": "카드"}},
            "출처": {"select": {"name": "카드명세서"}},
            "메모": {"rich_text": [{"text": {"content": memo}}]},
        })
        state[text_hash] = {"parsed": True, "card": m.group("issuer"), "cancelled_merchant": merchant, "amount": -amount, "date": date_iso}
        save_state(state)
        print(f"Recorded cancellation ({issuer_label}): {merchant} -{amount:,.0f}원 on {date_iso}")
        return

    m = AUTOPAY_PATTERN.search(SMS_TEXT)
    if m:
        amount = float(m.group("amount").replace(",", ""))
        merchant = m.group("merchant").strip()
        mm, dd = m.group("date").split("/")
        date_iso = f"{year}-{mm}-{dd}"
        category, note = resolve_category(merchant)
        memo = "\n".join([
            f"자동결제 문자입력 ({m.group('issuer')} 끝{m.group('mask')}) - {note}",
            SMS_TEXT,
        ])
        create_page({
            "항목": {"title": [{"text": {"content": merchant}}]},
            "날짜": {"date": {"start": date_iso}},
            "금액": {"number": amount},
            "카테고리": {"select": {"name": category}},
            "결제수단": {"select": {"name": "카드"}},
            "출처": {"select": {"name": "카드명세서"}},
            "메모": {"rich_text": [{"text": {"content": memo}}]},
        })
        state[text_hash] = {"parsed": True, "card": m.group("issuer"), "merchant": merchant, "amount": amount, "date": date_iso}
        save_state(state)
        print(f"Recorded (자동결제, {m.group('issuer')}): {merchant} {amount:,.0f}원 on {date_iso}")
        return

    m = LOTTE_PATTERN.search(SMS_TEXT)
    if m:
        amount = float(m.group("amount").replace(",", ""))
        merchant = m.group("merchant").strip()
        payment = m.group("payment")
        mm, dd = m.group("date").split("/")
        date_iso = f"{year}-{mm}-{dd}"
        category, note = resolve_category(merchant)
        memo = "\n".join([
            f"문자 자동입력 (롯데카드 끝{m.group('mask')}, {payment}) - {note}",
            SMS_TEXT,
        ])
        create_page({
            "항목": {"title": [{"text": {"content": merchant}}]},
            "날짜": {"date": {"start": date_iso}},
            "금액": {"number": amount},
            "카테고리": {"select": {"name": category}},
            "결제수단": {"select": {"name": "카드"}},
            "출처": {"select": {"name": "카드명세서"}},
            "메모": {"rich_text": [{"text": {"content": memo}}]},
        })
        state[text_hash] = {"parsed": True, "card": "롯데", "merchant": merchant, "amount": amount, "date": date_iso}
        save_state(state)
        print(f"Recorded (롯데카드): {merchant} {amount:,.0f}원 on {date_iso}")
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
        category, note = resolve_category(merchant)
        rate = fetch_krw_rate(date_iso, currency)
        if rate is not None:
            krw_amount = round(fx_amount * rate)
            title = merchant
            memo = "\n".join([
                f"하나카드 해외결제 - {currency}{fx_amount:,.2f} → 자동 환율({date_iso} ECB 기준 1{currency}={rate:,.2f}원) 적용 "
                f"- 카드사 실제 청구액(수수료 포함)과 다를 수 있음, {note}",
                SMS_TEXT,
            ])
            properties = {
                "항목": {"title": [{"text": {"content": title}}]},
                "날짜": {"date": {"start": date_iso}},
                "금액": {"number": krw_amount},
                "카테고리": {"select": {"name": category}},
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
                "카테고리": {"select": {"name": category}},
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
