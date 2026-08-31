import json
import os
import urllib.request

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
TRACKER_DB_ID = "72e1dc70-53c2-4ea5-a06c-5338d1347c2b"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

STOCKS = [
    ("005930", "삼성전자", "메모리"),
    ("005935", "삼성전자우", "메모리"),
    ("402340", "SK스퀘어", "지주사"),
    ("000660", "SK하이닉스(참고)", "메모리"),
]

DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.daum.net/",
}


def fetch_json_with_headers(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_sox():
    data = fetch_json_with_headers("https://finance.daum.net/api/quotes/US.SOX", DAUM_HEADERS)
    close_val = float(data["tradePrice"])
    ratio = round(float(data["changeRate"]) * 100, 2)
    trade_date = data.get("date")  # US session date, e.g. "2026-07-29"
    return close_val, ratio, trade_date


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_index(item_code):
    # NOTE: Naver's index "compareToPreviousPrice.code" / "fluctuationsRatio"
    # were found to report an incorrect direction/sign when the automation
    # runs outside normal market hours (e.g. after midnight due to the
    # GitHub Actions scheduling delay) -- on 2026-08-04's overnight run this
    # silently flipped a -5.12% KOSPI drop into a reported +5.12% gain.
    # This endpoint has no reliable numeric previous-close field either, so
    # instead of trusting Naver's sign at all, the ratio is computed by the
    # caller from our own previously recorded close (see get_last_close).
    data = fetch_json(f"https://m.stock.naver.com/api/index/{item_code}/basic")
    close_val = float(data["closePrice"].replace(",", ""))
    trade_date = data["localTradedAt"][:10]
    return close_val, trade_date


def notify_failure(message):
    # Previously check_stock/check_index/check_sox failures were only printed to
    # the (unwatched) Actions log, so weeks of silent gaps went unnoticed. Push
    # a real alert instead so a failed fetch actually surfaces.
    if not NTFY_TOPIC:
        print(f"(NTFY_TOPIC not set, can't push failure alert) {message}")
        return
    payload = {"topic": NTFY_TOPIC, "title": "반도체 트래커 조회 실패 ⚠️", "message": message}
    req = urllib.request.Request(
        "https://ntfy.sh",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"Failure alert push also failed: {e}")


def call_notion(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_last_close(name, before_date):
    query_body = {
        "filter": {
            "and": [
                {"property": "종목", "title": {"equals": name}},
                {"property": "날짜", "date": {"before": before_date}},
            ]
        },
        "sorts": [{"property": "날짜", "direction": "descending"}],
        "page_size": 1,
    }
    result = call_notion("POST", f"/databases/{TRACKER_DB_ID}/query", query_body)
    results = result.get("results", [])
    if not results:
        return None
    return results[0]["properties"]["종가"]["number"]


def already_recorded(name, date_str):
    query_body = {
        "filter": {
            "and": [
                {"property": "종목", "title": {"equals": name}},
                {"property": "날짜", "date": {"equals": date_str}},
            ]
        }
    }
    result = call_notion("POST", f"/databases/{TRACKER_DB_ID}/query", query_body)
    return bool(result.get("results"))


def check_stock(code, name):
    # NOTE: previously used a recursive search for any dict containing
    # "closePrice"+"compareToPreviousClosePrice", which could match a stale
    # nested block elsewhere in the response instead of today's actual
    # trading data. dealTrendInfos[0] is explicitly today's entry (bizdate).
    data = fetch_json(f"https://m.stock.naver.com/api/stock/{code}/integration")
    today_block = data["dealTrendInfos"][0]

    close_val = float(today_block["closePrice"].replace(",", ""))
    bizdate = today_block["bizdate"]  # e.g. "20260803" -- the real KST trade date,
    # NOT necessarily "today" if the automation ran late (GitHub Actions delay bug)
    trade_date = f"{bizdate[0:4]}-{bizdate[4:6]}-{bizdate[6:8]}"

    # Sign comes purely from comparing two numeric closes -- NOT from the
    # "compareToPreviousPrice.code" field, which was found unreliable (see
    # check_index note above; the same off-hours flakiness can affect stocks).
    last_close = None
    try:
        last_close_str = next(
            item["value"] for item in data.get("totalInfos", []) if item.get("code") == "lastClosePrice"
        )
        last_close = float(last_close_str.replace(",", ""))
    except (StopIteration, KeyError, ValueError):
        pass

    ratio = ((close_val - last_close) / last_close * 100) if last_close else 0.0

    return close_val, round(ratio, 2), trade_date


def main():
    for code, name, sector in STOCKS:
        try:
            close_val, ratio, trade_date = check_stock(code, name)
        except Exception as e:
            print(f"{name} 조회 실패: {e}")
            notify_failure(f"{name} 종가 조회 실패 - {e}")
            continue

        if already_recorded(name, trade_date):
            print(f"{name} {trade_date}: 이미 기록됨, 건너뜀")
            continue

        body = {
            "parent": {"database_id": TRACKER_DB_ID},
            "properties": {
                "종목": {"title": [{"text": {"content": name}}]},
                "날짜": {"date": {"start": trade_date}},
                "종가": {"number": close_val},
                "등락률": {"number": ratio},
                "섹터": {"select": {"name": sector}},
            },
        }
        call_notion("POST", "/pages", body)
        print(f"{name} {trade_date}: {close_val}원 ({ratio}%) 기록 완료")

    try:
        kospi_close, kospi_date = check_index("KOSPI")
    except Exception as e:
        print(f"코스피지수 조회 실패: {e}")
        notify_failure(f"코스피지수 조회 실패 - {e}")
    else:
        if already_recorded("코스피지수", kospi_date):
            print(f"코스피지수 {kospi_date}: 이미 기록됨, 건너뜀")
        else:
            prev_close = get_last_close("코스피지수", kospi_date)
            kospi_ratio = round((kospi_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            body = {
                "parent": {"database_id": TRACKER_DB_ID},
                "properties": {
                    "종목": {"title": [{"text": {"content": "코스피지수"}}]},
                    "날짜": {"date": {"start": kospi_date}},
                    "종가": {"number": kospi_close},
                    "등락률": {"number": kospi_ratio},
                    "섹터": {"select": {"name": "지수"}},
                },
            }
            call_notion("POST", "/pages", body)
            print(f"코스피지수 {kospi_date}: {kospi_close} ({kospi_ratio}%) 기록 완료")

    try:
        sox_close, sox_ratio, sox_date = check_sox()
    except Exception as e:
        print(f"필라델피아반도체지수(SOX) 조회 실패: {e}")
        notify_failure(f"필라델피아반도체지수(SOX) 조회 실패 - {e}")
    else:
        query_body = {
            "filter": {
                "and": [
                    {"property": "종목", "title": {"equals": "필라델피아반도체지수(SOX)"}},
                    {"property": "날짜", "date": {"equals": sox_date}},
                ]
            }
        }
        existing = call_notion("POST", f"/databases/{TRACKER_DB_ID}/query", query_body)
        if existing.get("results"):
            print(f"SOX {sox_date}: 이미 기록됨, 건너뜀")
            return

        body = {
            "parent": {"database_id": TRACKER_DB_ID},
            "properties": {
                "종목": {"title": [{"text": {"content": "필라델피아반도체지수(SOX)"}}]},
                "날짜": {"date": {"start": sox_date or today}},
                "종가": {"number": sox_close},
                "등락률": {"number": sox_ratio},
                "섹터": {"select": {"name": "지수"}},
            },
        }
        call_notion("POST", "/pages", body)
        print(f"SOX {sox_date}: {sox_close} ({sox_ratio}%) 기록 완료")


if __name__ == "__main__":
    main()
