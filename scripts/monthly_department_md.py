import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
API_BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

DEPT_DB_ID = "67dcd9b8-3d97-4db8-b182-c5974d787c0c"
SNAPSHOT_PARENT_PAGE_ID = "3ab1811a-40e9-81b1-ba69-ffded40da4ea"
KST = timezone(timedelta(hours=9))


def call(method, path, body=None):
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_database_all(db_id):
    results = []
    body = {}
    while True:
        resp = call("POST", f"/databases/{db_id}/query", body)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        body = {"start_cursor": resp["next_cursor"]}
    return results


def rich_text_plain(rt_list):
    return "".join(rt.get("plain_text", "") for rt in (rt_list or []))


def chunk_rich_text(text, size=1900):
    if not text:
        text = "(지침 미작성)"
    chunks = [text[i:i + size] for i in range(0, len(text), size)]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def heading_block(content):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": content}}]}}


def code_block(text):
    return {"object": "block", "type": "code", "code": {"rich_text": chunk_rich_text(text), "language": "markdown"}}


def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}


def build_department_blocks():
    rows = query_database_all(DEPT_DB_ID)
    blocks = []
    dept_count = 0
    for row in rows:
        props = row["properties"]
        active = props.get("활성", {}).get("checkbox", False)
        if not active:
            continue
        name = rich_text_plain(props.get("부서명", {}).get("title", []))
        md = rich_text_plain(props.get("지침MD", {}).get("rich_text", []))
        blocks.append(heading_block(f"📁 {name}"))
        blocks.append(code_block(md))
        blocks.append(divider_block())
        dept_count += 1
    return blocks, dept_count


def create_snapshot_page(title, blocks):
    body = {
        "parent": {"page_id": SNAPSHOT_PARENT_PAGE_ID},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": blocks[:100],
    }
    page = call("POST", "/pages", body)
    remaining = blocks[100:]
    while remaining:
        call("PATCH", f"/blocks/{page['id']}/children", {"children": remaining[:100]})
        remaining = remaining[100:]
    return page


def send_ntfy(title, message, url):
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Click": url,
        },
        method="POST",
    )
    urllib.request.urlopen(req)


def main():
    now_kst = datetime.now(KST)
    title = now_kst.strftime("%Y-%m")
    blocks, dept_count = build_department_blocks()
    page = create_snapshot_page(title, blocks)
    send_ntfy(
        f"📋 {title} 부서 지침 스냅샷 준비됐어요",
        f"{dept_count}개 부서 지침 MD가 정리됐어요. 눌러서 확인하고 claude.ai Projects에 복사/붙여넣기 하세요.",
        page["url"],
    )
    print(f"Created snapshot page: {page['url']} ({dept_count} departments)")


if __name__ == "__main__":
    main()
