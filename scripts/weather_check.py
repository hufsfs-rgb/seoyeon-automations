import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HISTORY_PATH = "data/weather-history.json"
LOCATION = "Incheon"
NAVER_QUERY_URL = "https://search.naver.com/search.naver?query={}"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_wttr():
    req = urllib.request.Request(f"https://wttr.in/{LOCATION}?format=j1", headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cur = data["current_condition"][0]
    return {
        "temp_c": float(cur["temp_C"]),
        "humidity": int(cur["humidity"]),
        "wind_kmph": float(cur["windspeedKmph"]),
        "desc": cur["weatherDesc"][0]["value"],
    }


def fetch_naver_dust():
    try:
        req = urllib.request.Request(
            NAVER_QUERY_URL.format(urllib.parse.quote("인천 송도 미세먼지")), headers=UA
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        pm10 = re.search(r"미세먼지[^<]*?(좋음|보통|나쁨|매우나쁨)", html)
        pm25 = re.search(r"초미세먼지[^<]*?(좋음|보통|나쁨|매우나쁨)", html)
        return {
            "pm10": pm10.group(1) if pm10 else None,
            "pm25": pm25.group(1) if pm25 else None,
        }
    except Exception as e:
        print(f"[warn] dust scrape failed: {e}")
        return {"pm10": None, "pm25": None}


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_history(history):
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history[-14:], f, ensure_ascii=False, indent=2)


def diff_str(today, yesterday, unit, fmt="{:+.1f}"):
    if yesterday is None:
        return ""
    d = today - yesterday
    if abs(d) < 0.05:
        return " (어제와 비슷)"
    return f" (어제보다 {fmt.format(d)}{unit})"


def main():
    tz = ZoneInfo("Asia/Seoul")
    today_str = datetime.now(tz).date().isoformat()

    weather = fetch_wttr()
    dust = fetch_naver_dust()
    history = load_history()

    yesterday_entry = history[-1] if history else None

    temp_diff = diff_str(weather["temp_c"], yesterday_entry["temp_c"] if yesterday_entry else None, "도")
    hum_diff = diff_str(weather["humidity"], yesterday_entry["humidity"] if yesterday_entry else None, "%")
    wind_diff = diff_str(weather["wind_kmph"], yesterday_entry["wind_kmph"] if yesterday_entry else None, "km/h")

    lines = [
        f"오늘 날씨: {weather['desc']}, {weather['temp_c']:.0f}도{temp_diff}",
        f"습도 {weather['humidity']}%{hum_diff} / 바람 {weather['wind_kmph']:.0f}km/h{wind_diff}",
    ]
    if dust["pm10"] or dust["pm25"]:
        lines.append(f"미세먼지 {dust['pm10'] or '정보없음'} / 초미세먼지 {dust['pm25'] or '정보없음'}")

    # persist today's reading for tomorrow's comparison (only if not already recorded today)
    if not history or history[-1].get("date") != today_str:
        history.append({
            "date": today_str,
            "temp_c": weather["temp_c"],
            "humidity": weather["humidity"],
            "wind_kmph": weather["wind_kmph"],
        })
        save_history(history)

    summary = "\n".join(lines)
    print(summary)

    # also expose for the workflow to pick up via output file
    with open("weather_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)


if __name__ == "__main__":
    main()
