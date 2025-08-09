import os
from pathlib import Path
from urllib.parse import quote
import requests

WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
REPO    = os.environ.get("GITHUB_REPOSITORY")
BRANCH  = os.environ.get("GITHUB_REF_NAME", "main")

def latest_dir() -> Path | None:
    root = Path("shots")
    if not root.exists(): return None
    dirs = [p for p in root.iterdir() if p.is_dir()]
    return sorted(dirs)[-1] if dirs else None

def raw_url(p: Path) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{quote(str(p))}"

def main():
    if not WEBHOOK:
        print("No SLACK_WEBHOOK_URL secret.")
        return

    d = latest_dir()
    if not d:
        requests.post(WEBHOOK, json={"text":"📸 오늘 캡처 없음"})
        return

    imgs = sorted(d.glob("*.png"))
    if not imgs:
        requests.post(WEBHOOK, json={"text":f"📸 {d.name} 캡처 이미지 없음"})
        return

    blocks = [{"type":"header","text":{"type":"plain_text","text":f"📸 경쟁사 메인 캡처 - {d.name}"}}]
    for p in imgs[:10]:
        site = p.stem
        blocks += [
            {"type":"section","text":{"type":"mrkdwn","text":f"*{site}*"}},
            {"type":"image","image_url": raw_url(p), "alt_text": site}
        ]

    r = requests.post(WEBHOOK, json={"text":"Visual monitor", "blocks": blocks}, timeout=20)
    print("Slack response:", r.status_code, r.text)

if __name__ == "__main__":
    main()
