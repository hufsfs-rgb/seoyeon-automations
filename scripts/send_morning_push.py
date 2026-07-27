import json
import os
import urllib.request

NTFY_URL = "https://ntfy.sh"


def main():
    weather_line = ""
    if os.path.exists("weather_summary.txt"):
        with open("weather_summary.txt", encoding="utf-8") as f:
            weather_line = f.read().strip()

    message = "오늘의 브리핑이 준비됐어요! 노션에서 확인해주세요 :)"
    if weather_line:
        message += "\n\n" + weather_line

    payload = {
        "topic": os.environ["NTFY_TOPIC"],
        "title": "서연의 모닝 브리핑 ☀️",
        "message": message,
        "click": "https://app.notion.com/p/3a91811a40e981648133f0ab3f5863ee",
    }
    req = urllib.request.Request(
        NTFY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))


if __name__ == "__main__":
    main()
