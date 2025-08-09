import os
import requests
from pathlib import Path

def main():
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("No Slack webhook URL set.")
        return

    today_dir = Path("shots") / Path().cwd().name
    if not today_dir.exists():
        today_dir = Path("shots")

    attachments = []
    for img_path in sorted(today_dir.glob("*.png")):
        attachments.append({
            "title": img_path.name,
            "image_url": f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY')}/main/{img_path}"
        })

    payload = {"text": f"📸 Daily Screenshots ({today_dir.name})", "attachments": attachments}
    resp = requests.post(webhook_url, json=payload)
    print(f"Slack response: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    main()
