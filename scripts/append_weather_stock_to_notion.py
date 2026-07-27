import json
import os
import urllib.request

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
BRIEFING_PAGE_ID = "3a91811a-40e9-8164-8133-f0ab3f5863ee"


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def rich_text(content):
    return [{"type": "text", "text": {"content": content}}]


def paragraph_block(content):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(content)}}


def heading_block(content):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(content)}}


def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}


def main():
    weather = read_file("weather_summary.txt")
    stocks = read_file("stock_summary.txt")

    if not weather and not stocks:
        print("No weather/stock data to append.")
        return

    blocks = [divider_block(), heading_block("📊 날씨 · 주식 · 환율")]
    if weather:
        blocks.append(paragraph_block(weather))
    if stocks:
        blocks.append(paragraph_block(stocks))

    call("PATCH", f"/blocks/{BRIEFING_PAGE_ID}/children", {"children": blocks})
    print("Appended weather/stock section to Notion briefing page.")


if __name__ == "__main__":
    main()
