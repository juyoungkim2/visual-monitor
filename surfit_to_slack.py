import os, json, re, time
import datetime as dt
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ===== 설정 =====
SURFIT_BASE = "https://www.surfit.io"
LIST_PAGES = [
    "https://www.surfit.io/",
    "https://www.surfit.io/discover",
    "https://www.surfit.io/discover?sort=new",
]
MAX_ITEMS = 8                 # 한 번에 보낼 최대 개수
CACHE = Path(".cache/surfit_seen.json")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SurfitSlackBot/1.4",
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

# ---------- 공통 추출 유틸 ----------
def walk_collect(node, urls: set):
    """JSON 트리 전체를 돌며 /article/ 또는 슬러그 모양의 문자열을 수집"""
    if isinstance(node, dict):
        for v in node.values(): walk_collect(v, urls)
    elif isinstance(node, list):
        for v in node: walk_collect(v, urls)
    elif isinstance(node, str):
        s = node.strip()
        if s.startswith("/article/"):
            urls.add(urljoin(SURFIT_BASE, s))
        elif re.fullmatch(r"[A-Za-z0-9\-_]{8,}", s):
            urls.add(urljoin(SURFIT_BASE, f"/article/{s}"))

def extract_from_next_script(html: str):
    """<script id="__NEXT_DATA__"> JSON에서 추출 (type 유무 상관없음)"""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.text:
        return []
    try:
        data = json.loads(tag.text)
    except Exception:
        return []
    urls = set()
    walk_collect(data, urls)
    return list(urls)

def find_build_id(html: str):
    """HTML 내 buildId 추출 (Next.js)"""
    m = re.search(r'"buildId"\s*:\s*"([A-Za-z0-9\-_]+)"', html)
    if m:
        return m.group(1)
    # link preload로도 노출되는 경우
    m2 = re.search(r"/_next/data/([A-Za-z0-9\-_]+)/", html)
    if m2:
        return m2.group(1)
    return None

def route_to_data_path(route: str):
    """페이지 경로를 Next data JSON 경로로 변환"""
    parsed = urlparse(route)
    path = parsed.path or "/"
    q = parsed.query

    if path == "/" or path == "":
        json_path = "/index.json"
    else:
        # /discover -> /discover.json
        if not path.endswith(".json"):
            json_path = f"{path}.json"
        else:
            json_path = path

    if q:
        json_path = f"{json_path}?{q}"
    return json_path

def extract_via_next_data_api(html: str, route_url: str):
    """buildId로 /_next/data/{buildId}/...json을 요청해 추출"""
    build = find_build_id(html)
    if not build:
        return []

    data_path = route_to_data_path(route_url)
    data_url = urljoin(SURFIT_BASE, f"/_next/data/{build}{data_path}")
    try:
        r = fetch(data_url)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    urls = set()
    walk_collect(data, urls)
    return list(urls)

def extract_article_urls_from_html(html: str, route_url: str):
    """정규식 + __NEXT_DATA__ + /_next/data/BUILD/*.json 3중 백업"""
    urls = set()

    # 1) 정규식(직접 노출 대비)
    for u in re.findall(r"https?://www\.surfit\.io/article/[A-Za-z0-9\-_]+", html):
        urls.add(u)
    for u in re.findall(r'"(/article/[A-Za-z0-9\-_]+)"', html):
        urls.add(urljoin(SURFIT_BASE, u))

    # 2) __NEXT_DATA__ 스크립트
    for u in extract_from_next_script(html):
        urls.add(u)

    # 3) buildId 기반 JSON
    if not urls:
        for u in extract_via_next_data_api(html, route_url):
            urls.add(u)

    return list(urls)

# ---------- 메타/슬랙 ----------
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
    now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"text": f"[Surfit Bot] ping {now}"}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    print("[DEBUG] Slack response (ping):", r.status_code, r.text[:200])
    return r.ok

# ---------- 메인 ----------
def main():
    ensure_cache()
    seen = load_seen()

    try:
        send_ping()
    except Exception as e:
        print("[WARN] ping failed:", e)

    candidates = []
    for page in LIST_PAGES:
        try:
            res = fetch(page)
            print(f"[DEBUG] fetch {page} -> {res.status_code}")
            if res.status_code == 200 and res.text:
                urls = extract_article_urls_from_html(res.text, page)
                print(f"[DEBUG] found {len(urls)} article urls from {page}")
                candidates.extend(urls)
        except Exception as e:
            print("[ERROR] list fetch error:", page, e)
        time.sleep(0.5)

    # 중복 제거 (앞쪽 우선)
    uniq, s = [], set()
    for u in candidates:
        if u not in s:
            s.add(u); uniq.append(u)

    new_urls = [u for u in uniq if article_id(u) not in seen]
    print(f"[DEBUG] total uniq: {len(uniq)}, new: {len(new_urls)}")

    send_urls = new_urls if new_urls else uniq[:5]
    if not send_urls:
        print("[ERROR] No article URLs extracted at all. Stop.")
        return

    ok = post_to_slack(build_blocks(send_urls))

    if ok and new_urls:
        for u in new_urls: seen.add(article_id(u))
        save_seen(seen)
        print(f"[DEBUG] cache updated, total seen={len(seen)}")
    else:
        print("[DEBUG] no cache update")

if __name__ == "__main__":
    main()
