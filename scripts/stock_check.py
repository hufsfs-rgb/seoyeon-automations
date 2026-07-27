import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

STOCKS = [
    ("402340", "SK스퀘어"),
    ("005930", "삼성전자"),
    ("005935", "삼성전자우"),
    ("282330", "BGF리테일"),
    ("055550", "신한지주"),
]


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_signed_num(s):
    # values already come with +/- sign from Naver, just strip commas for compactness
    return s.replace(",", "")


def check_stock(code, fallback_name):
    data = fetch_json(f"https://m.stock.naver.com/api/stock/{code}/integration")
    name = data.get("stockName") or data.get("dealTrendInfos", [{}])[0].get("stockName") or fallback_name

    # price info can be under different keys depending on API version; search recursively
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
    change = price_block.get("compareToPreviousClosePrice", "")
    ratio = price_block.get("fluctuationsRatio", "")
    rising = price_block.get("compareToPreviousPrice", {}).get("code") if isinstance(price_block.get("compareToPreviousPrice"), dict) else None
    sign = "+" if rising == "2" else ("-" if rising == "5" else "")

    # investor trend: find list of dicts containing foreignerPureBuyQuant
    def find_trend_list(obj):
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and "foreignerPureBuyQuant" in obj[0]:
                return obj
            for item in obj:
                r = find_trend_list(item)
                if r:
                    return r
        elif isinstance(obj, dict):
            for v in obj.values():
                r = find_trend_list(v)
                if r:
                    return r
        return None

    trend_list = find_trend_list(data) or []
    latest = trend_list[0] if trend_list else {}
    frgn = fmt_signed_num(latest.get("foreignerPureBuyQuant", "0"))
    org = fmt_signed_num(latest.get("organPureBuyQuant", "0"))
    ind = fmt_signed_num(latest.get("individualPureBuyQuant", "0"))

    return f"{name} {close}원({sign}{ratio}%) | 외인{frgn} 기관{org} 개인{ind}"


def check_fx():
    data = fetch_json("https://api.stock.naver.com/marketindex/exchange/FX_USDKRW")
    info = data.get("exchangeInfo", {})
    close = info.get("closePrice", "?")
    fluct = info.get("fluctuations", "")
    ftype = info.get("fluctuationsType", {}).get("text", "")
    return f"USD/KRW {close}원 ({ftype} {fluct})"


def main():
    lines = []
    for code, name in STOCKS:
        try:
            lines.append(check_stock(code, name))
        except Exception as e:
            lines.append(f"{name} 조회 실패: {e}")
    try:
        lines.append(check_fx())
    except Exception as e:
        lines.append(f"환율 조회 실패: {e}")

    summary = "\n".join(lines)
    print(summary)
    with open("stock_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)


if __name__ == "__main__":
    main()
