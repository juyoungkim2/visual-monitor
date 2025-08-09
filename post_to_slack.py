import os, json, datetime, urllib.parse, requests, pathlib
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME","main")
today = datetime.datetime.now().strftime("%Y-%m-%d")
idx = pathlib.Path("shots")/today/"_index.json"
items = json.load(open(idx, encoding="utf-8")) if idx.exists() else []
def raw_url(p): return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{urllib.parse.quote(p)}"
blocks=[{"type":"header","text":{"type":"plain_text","text":f"📸 경쟁사 메인 비주얼 - {today}"}}]
for it in items:
  blocks += [
    {"type":"section","text":{"type":"mrkdwn","text":f"*{it['name']}*\n<{it['url']}|사이트 바로가기>"}},
    {"type":"image","image_url":raw_url(it["path"]), "alt_text":it["name"]}
  ]
if not items: blocks.append({"type":"section","text":{"type":"mrkdwn","text":"업데이트 없음"}})
requests.post(WEBHOOK, json={"text":"visual monitor", "blocks":blocks}, timeout=20)
print("posted")
