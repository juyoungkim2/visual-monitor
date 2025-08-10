import os, json, re, time
import datetime as dt
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ===== 설정 =====
SURFIT_BASE = "https://www.surfit.io"
LIST_PAGES = [
    "https://www.surfit.io/",
    "https://www.surfit.io/discover",
]
MAX_ITEMS = 8                 # 한 번에 보낼 최대 개수
CACHE = Path(".cache/surfit_seen.json")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SurfitSlackBot/1.2",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
TIMEOUT = 15
# =================

def ensure_cache():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        CACHE.write_text("[]", encoding="utf-8")

def fetch(url: str):
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT)

def article_id(url: str) -> str:
    m = re.search(r"/article/([A-Za-z0-9\-_]+)", url)
    return m.group(1) if m else url

def load_seen():
    try:
        return set(json.loads(CACHE.read_text(encoding="utf-8")))
    except Exception:
        return set()

def save_seen(seen):
    CACHE.write_text(
        json.dumps(sorted(list(seen))[-500:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def extract_article_urls_from_html(html: str):
    """JS 렌더링 없이 /article/ 링크만 정규식으로 수집"""
    urls = set()

    # 절대경로
    for u in re.findall(r"https?://www\.surfit\.io/article/[A-Za-z0-9\-_]+", html):
        urls.add(u)

    # 상대경로
    for u in re.findall(r'"(/article/[A-Za-z0-9\-_]+)"', html):
        urls.add(urljoin(SURFIT_BASE, u))

    return list(urls)

def parse_meta(url: str):
    """개별 글에서 og:title / og:description 읽기"""
    try:
        r = fetch(url)
        if r.status_code != 200:
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")

        title = None
        desc = None

        ogt = soup.find("meta", attrs={"property": "og:title"})
        if ogt and ogt.get("content"):
            title = ogt.get("content").strip()
        if not title and soup.title and soup.title.text:
            title = soup.title.text.strip()

        ogd = soup.find("meta", attrs={"property": "og:description"})
        if ogd and ogd.get("content"):
            desc = ogd.get("content").strip()
        if not desc:
            md = soup.find("meta", attrs={"name": "description"})
            if md and md.get("content"):
                desc = md.get("content").strip()

        if desc:
            desc = " ".join(desc.split())[:280]

        return title, desc
    except Exception:
        return None, None

def build_blocks(urls):
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
    blocks = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"🧩 Surfit 신규 아티클 - {today}"}
    }]

    for url in urls[:MAX_ITEMS]:
        title, desc = parse_meta(url)
        if not title:
            title = f"Surfit Article {article_id(url)}"
        text = f"*<{url}|{title}>*"
        if desc:
            text += f"\n{desc}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    return blocks

def post_to_slack(blocks) -> bool:
    if not WEBHOOK:
        print("[ERROR] SLACK_WEBHOOK_URL not set")
        return False

    payload = {"text": "Surfit 신규 아티클", "blocks": blocks}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    print("[DEBUG] Slack response (blocks):", r.status_code, r.text[:200])

    if r.ok and r.text.strip() in ("ok", ""):
        return True

    # 블록 실패 시 텍스트 폴백
    try:
        lines = []
        for b in blocks[1:]:
            if b.get("type") == "section":
                lines.append(b["text"]["text"])
        fallback = {"text": "🧩 Surfit 신규 아티클\n\n" + "\n\n".join(lines[:10])}
        r2 = requests.post(WEBHOOK, json=fallback, timeout=20)
        print("[DEBUG] Slack response (fallback):", r2.status_code, r2.text[:200])
        return r2.ok and r2.text.strip() in ("ok", "")
    except Exception as e:
        print("[ERROR] Slack fallback error:", e)
        return False

def send_ping():
    """웹훅 동작 확인용 테스트 메시지(기사 0건이어도 전송)"""
    now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"text": f"[Surfit Bot] ping {now}"}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    print("[DEBUG] Slack response (ping):", r.status_code, r.text[:200])
    return r.ok

def main():
    ensure_cache()
    seen = load_seen()

    # 0) 웹훅 핑(최초 1회 확인용) — 실패해도 계속 진행
    try:
        send_ping()
    except Exception as e:
        print("[WARN] ping failed:", e)

    # 1) 리스트에서 링크 수집
    candidates = []
    for page in LIST_PAGES:
        try:
            res = fetch(page)
            print(f"[DEBUG] fetch {page} -> {res.status_code}")
            if res.status_code == 200 and res.text:
                urls = extract_article_urls_from_html(res.text)
                print(f"[DEBUG] found {len(urls)} article urls from {page}")
                candidates.extend(urls)
        except Exception as e:
            print("[ERROR] list fetch error:", page, e)
        time.sleep(0.5)

    # 중복 제거 (앞쪽 우선)
    uniq = []
    seen_urls = set()
    for u in candidates:
        if u not in seen_urls:
            seen_urls.add(u)
            uniq.append(u)

    # 2) 신규만 필터
    new_urls = [u for u in uniq if article_id(u) not in seen]
    print(f"[DEBUG] total uniq: {len(uniq)}, new: {len(new_urls)}")

    # 3) 보낼 목록 결정 (신규 없으면 상위 5개라도 보내서 형태 확인)
    send_urls = new_urls if new_urls else uniq[:5]
    if not send_urls:
        print("[ERROR] No article URLs extracted at all. Stop.")
        return

    # 4) 슬랙 전송
    ok = post_to_slack(build_blocks(send_urls))

    # 5) 성공 시 캐시 업데이트(신규만)
    if ok and new_urls:
        for u in new_urls:
            seen.add(article_id(u))
        save_seen(seen)
        print(f"[DEBUG] cache updated, total
