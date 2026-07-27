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

DIARY_DB_ID = "3f99d169-743d-4361-b995-1e8e25e77e13"
CONTACTS_DB_ID = "d1005bc7-6f19-4214-accc-bb1ff4b40955"
BRIEFING_PAGE_ID = "3a91811a-40e9-8164-8133-f0ab3f5863ee"


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


def backup_diary():
    rows = query_database_all(DIARY_DB_ID)
    entries = []
    for row in rows:
        props = row["properties"]
        title = rich_text_plain(props.get("날짜", {}).get("title", []))
        content = rich_text_plain(props.get("일기", {}).get("rich_text", []))
        entries.append((title, content))
    entries.sort(key=lambda x: x[0])
    lines = ["# 서연의 하루일기 백업", ""]
    for date_str, content in entries:
        lines.append(f"## {date_str}")
        lines.append("")
        lines.append(content)
        lines.append("")
    os.makedirs("backups", exist_ok=True)
    with open("backups/diary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def backup_contacts():
    rows = query_database_all(CONTACTS_DB_ID)
    contacts = []
    for row in rows:
        p = row["properties"]
        contacts.append({
            "이름": rich_text_plain(p.get("이름", {}).get("title", [])),
            "전화번호": p.get("전화번호", {}).get("phone_number"),
            "이메일": p.get("이메일", {}).get("email"),
            "회사/소속": rich_text_plain(p.get("회사/소속", {}).get("rich_text", [])),
            "직책": rich_text_plain(p.get("직책", {}).get("rich_text", [])),
            "카테고리": [c["name"] for c in p.get("카테고리", {}).get("multi_select", [])],
            "메모": rich_text_plain(p.get("메모", {}).get("rich_text", [])),
            "만난 경위": rich_text_plain(p.get("만난 경위", {}).get("rich_text", [])),
        })
    os.makedirs("backups", exist_ok=True)
    with open("backups/contacts.json", "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)


def block_to_md(block):
    t = block["type"]
    data = block.get(t, {})
    text = rich_text_plain(data.get("rich_text", []))
    prefix = {
        "heading_1": "# ",
        "heading_2": "## ",
        "heading_3": "### ",
        "bulleted_list_item": "- ",
        "numbered_list_item": "1. ",
        "quote": "> ",
    }.get(t, "")
    return prefix + text if text else ""


def backup_briefing():
    resp = call("GET", f"/blocks/{BRIEFING_PAGE_ID}/children?page_size=100")
    lines = [block_to_md(b) for b in resp["results"]]
    lines = [l for l in lines if l]
    os.makedirs("backups", exist_ok=True)
    with open("backups/briefing_latest.md", "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines))


if __name__ == "__main__":
    backup_diary()
    backup_contacts()
    backup_briefing()
    print("Backup complete.")
