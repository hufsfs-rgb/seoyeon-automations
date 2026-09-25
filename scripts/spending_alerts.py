"""Real-time spending coach alerts, run right after each card SMS is recorded.

대표님 요청(2026-09-25): 소비를 그때그때 분석해서 과도한 소비가 있으면 알림 + 조언.
Three rule-based checks (no LLM call - cheap, instant, deterministic):
  1. 큰 결제      - single variable-spend payment >= BIG_PAYMENT_KRW
  2. 연속 결제    - same merchant hit for the 3rd time on the same day
  3. 카테고리 과속 - this month's category spend running >= PACE_RATIO x the
                    prorated average of the previous 3 months (once per
                    category per month, tracked in STATE_PATH)
Push text carries only amounts/merchant + a short tip - never income/assets
(ntfy topics are readable by anyone who knows the topic name).
"""
import calendar
import json
import os
import urllib.request
from datetime import date

LEDGER_DB_ID = "d066c98b-aa9b-40f3-86a6-b237db75d021"
STATE_PATH = "data/spending-alert-state.json"

BIG_PAYMENT_KRW = 150_000
SAME_MERCHANT_DAILY_COUNT = 3
PACE_RATIO = 1.3
# Pace alerts need a few days of data, otherwise one early purchase looks like
# a huge overspend against a tiny prorated budget.
PACE_MIN_DAY = 7

# Lumpy or non-discretionary categories - alerting on these just nags without
# anything 대표님 could realistically cut in the moment.
NO_ALERT_CATEGORIES = {"고정지출", "교육", "출장/여행", "경조사", "의료"}

TIPS = {
    "식비": "외식·배달이 몰리는 요일이 있는지 이번 주 리포트에서 같이 봐요.",
    "생활": "장바구니에 담아두고 하루 뒤에 결제하면 충동구매가 꽤 걸러져요.",
    "주유교통": "주유 할인 카드 혜택이나 주유 요일 할인을 한 번 확인해볼까요?",
    "문화/여가": "즐거운 지출이니 줄이기보단 이번 달 한도만 정해둬요.",
}


def _call(headers, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("https://api.notion.com/v1" + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _query_all(headers, filter_):
    rows, cursor = [], None
    while True:
        body = {"filter": filter_, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = _call(headers, "POST", f"/databases/{LEDGER_DB_ID}/query", body)
        rows.extend(resp.get("results", []))
        if not resp.get("has_more"):
            return rows
        cursor = resp.get("next_cursor")


def _amount(row):
    return row["properties"].get("금액", {}).get("number") or 0


def _prev_months(d, n):
    y, m = d.year, d.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return out


def _load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state):
    os.makedirs("data", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_big_payment(merchant, amount, category):
    if category in NO_ALERT_CATEGORIES or amount < BIG_PAYMENT_KRW:
        return None
    return (
        f"큰 결제 감지: {merchant}",
        f"{amount:,.0f}원 ({category}). 계획된 지출이었나요? 아니라면 이번 주 코칭 때 같이 짚어봐요.",
    )


def check_same_merchant(headers, merchant, date_iso):
    rows = _query_all(headers, {"and": [
        {"property": "항목", "title": {"equals": merchant}},
        {"property": "날짜", "date": {"equals": date_iso}},
    ]})
    positives = [r for r in rows if _amount(r) > 0]
    # Fire exactly on the Nth hit so a busy day produces one nudge, not five.
    if len(positives) != SAME_MERCHANT_DAILY_COUNT:
        return None
    total = sum(_amount(r) for r in positives)
    return (
        f"오늘 {merchant} {SAME_MERCHANT_DAILY_COUNT}번째 결제",
        f"오늘만 {len(positives)}건, 합계 {total:,.0f}원이에요. 한 번에 모아서 결제하면 충동구매가 확 줄어요!",
    )


def check_category_pace(headers, category, date_iso, state):
    if category in NO_ALERT_CATEGORIES or category == "기타":
        return None
    d = date.fromisoformat(date_iso)
    if d.day < PACE_MIN_DAY:
        return None
    this_ym = date_iso[:7]
    key = f"{this_ym}|{category}|pace"
    if state.get(key):
        return None

    past = _prev_months(d, 3)
    rows = _query_all(headers, {"and": [
        {"property": "카테고리", "select": {"equals": category}},
        {"or": [{"property": "연월", "select": {"equals": ym}} for ym in [this_ym] + past]},
    ]})
    totals = {}
    for r in rows:
        ym = (r["properties"].get("연월", {}).get("select") or {}).get("name")
        totals[ym] = totals.get(ym, 0) + _amount(r)
    avg = sum(totals.get(ym, 0) for ym in past) / len(past)
    if avg <= 0:
        return None
    days_in_month = calendar.monthrange(d.year, d.month)[1]
    expected_so_far = avg * d.day / days_in_month
    mtd = totals.get(this_ym, 0)
    if mtd < expected_so_far * PACE_RATIO:
        return None

    state[key] = date_iso
    projected = mtd / d.day * days_in_month
    tip = TIPS.get(category, "이번 주 코칭 리포트에서 원인을 같이 볼게요.")
    return (
        f"{category} 지출 과속 주의",
        f"이번 달 {category} {mtd:,.0f}원 (최근 3개월 평균 {avg:,.0f}원). "
        f"이 속도면 월말 약 {projected:,.0f}원 예상이에요. {tip}",
    )


def run_spending_alerts(headers, push, merchant, amount, category, date_iso):
    """Never raises - an alert failure must not break ledger recording."""
    if amount is None or amount <= 0:
        return
    state = _load_state()
    checks = [
        lambda: check_big_payment(merchant, amount, category),
        lambda: check_same_merchant(headers, merchant, date_iso),
        lambda: check_category_pace(headers, category, date_iso, state),
    ]
    for check in checks:
        try:
            alert = check()
        except Exception as e:
            print(f"Spending alert check failed: {e}")
            continue
        if alert:
            try:
                push(*alert)
                print("Spending alert pushed:", alert[0])
            except Exception as e:
                print(f"Spending alert push failed: {e}")
    _save_state(state)


if __name__ == "__main__":
    # Dry run against the real ledger without pushing or saving state:
    # SAMPLES="merchant|amount|category|YYYY-MM-DD;..." python3 scripts/spending_alerts.py
    headers = {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    for sample in os.environ["SAMPLES"].split(";"):
        merchant, amount, category, date_iso = sample.split("|")
        amount = float(amount)
        print(f"--- {sample}")
        print(" big :", check_big_payment(merchant, amount, category))
        print(" same:", check_same_merchant(headers, merchant, date_iso))
        print(" pace:", check_category_pace(headers, category, date_iso, {}))
