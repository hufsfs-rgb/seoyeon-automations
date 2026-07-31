import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
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
    data = fetch_json(f"https://m.stock.naver.com/api/index/{item_code}/basic")
    close_val = float(data["closePrice"].replace(",", ""))
    ratio_val = float(data["fluctuationsRatio"])
    rising = data.get("compareToPreviousPrice", {}).get("code")
    sign = -1 if rising == "5" else 1
    return close_val, round(sign * ratio_val, 2)


def call_notion(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_stock(code, name):
    data = fetch_json(f"https://m.stock.naver.com/api/stock/{code}/integration")

    def find_price_block(obj):
        if isinstance(obj, dict):
            if "closePrice" in obj and "compareToPreviousClosePrice" in obj:
                return obj
            for v in obj.values():
                r = find_price_block(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find_price_block(item)
                if r:
                    return r
        return None

    price_block = find_price_block(data) or {}
    close = price_block.get("closePrice", "?")
    change = price_block.get("compareToPreviousClosePrice", "0").lstrip("+-")
    rising = (
        price_block.get("compareToPreviousPrice", {}).get("code")
        if isinstance(price_block.get("compareToPreviousPrice"), dict)
        else None
    )
    sign = -1 if rising == "5" else 1

    close_val = float(str(close).replace(",", ""))
    change_val = float(str(change).replace(",", ""))
    signed_change = sign * change_val

    last_close = None
    try:
        last_close_str = next(
            item["value"] for item in data.get("totalInfos", []) if item.get("code") == "lastClosePrice"
        )
        last_close = float(last_close_str.replace(",", ""))
    except (StopIteration, KeyError, ValueError):
        pass
    if not last_close:
        last_close = close_val - signed_change

    ratio = (signed_change / last_close * 100) if last_close else 0.0

    return close_val, round(ratio, 2)


def main():
    tz = ZoneInfo("Asia/Seoul")
    today = datetime.now(tz).date().isoformat()

    for code, name, sector in STOCKS:
        try:
            close_val, ratio = check_stock(code, name)
        except Exception as e:
            print(f"{name} 조회 실패: {e}")
            continue

        body = {
            "parent": {"database_id": TRACKER_DB_ID},
            "properties": {
                "종목": {"title": [{"text": {"content": name}}]},
                "날짜": {"date": {"start": today}},
                "종가": {"number": close_val},
                "등락률": {"number": ratio},
                "섹터": {"select": {"name": sector}},
            },
        }
        call_notion("POST", "/pages", body)
        print(f"{name} {today}: {close_val}원 ({ratio}%) 기록 완료")

    try:
        kospi_close, kospi_ratio = check_index("KOSPI")
    except Exception as e:
        print(f"코스피지수 조회 실패: {e}")
    else:
        body = {
            "parent": {"database_id": TRACKER_DB_ID},
            "properties": {
                "종목": {"title": [{"text": {"content": "코스피지수"}}]},
                "날짜": {"date": {"start": today}},
                "종가": {"number": kospi_close},
                "등락률": {"number": kospi_ratio},
                "섹터": {"select": {"name": "지수"}},
            },
        }
        call_notion("POST", "/pages", body)
        print(f"코스피지수 {today}: {kospi_close} ({kospi_ratio}%) 기록 완료")

    try:
        sox_close, sox_ratio, sox_date = check_sox()
    except Exception as e:
        print(f"필라델피아반도체지수(SOX) 조회 실패: {e}")
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
