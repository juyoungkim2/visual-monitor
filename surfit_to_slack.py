import os, json, re, time
import datetime as dt
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ===== 설정 =====
SURFIT_BASE = "https://www.surfit.io"
LIST_PAGES = [
    "https://www.surfit.io/",
    "https://www.surfit.io/discover",
    "https://www.surfit.io/discover?sort=new",
]
# 사이트맵 후보들(서비스마다 이름 다를 수 있어 여러 개 시도)
SITEMAP_CANDIDATES = [
    "https://www.surfit.io/sitemap.xml",
    "https://www.surfit.io/sitemap_index.xml",
    "https://www.surfit.io/sitemap-0.xml",
    "https://www.surfit.io/sitemap-1.xml",
    "https://www.surfit.io/sitemap-articles.xml",
]

MAX_ITEMS = 8
CACHE = Path(".cache/surfit_seen.json")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

HEADERS = {
    # 브라우저 흉내 최대치(봇 차단 회피)
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT = 15
# =================

def ensure_cache():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        CACHE.write_text("[]", encoding="utf-8")

def fetch(url: str):
    # 일부 서버가 keep-alive/압축 때문에 응답 이상하게 주는 경우가 있어 Session 대신 단발 요청 유지
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

# ---------- 리스트(HTML/Next) 시도 ----------
def walk_collect(node, out: set):
    if isinstance(node, dict):
        for v in node.values(): walk_collect(v, out)
    elif isinstance(node, list):
        for v in node: walk_collect(v, out)
    elif isinstance(node, str):
        s = node.strip()
        if s.startswith("/article/"):
            out.add(urljoin(SURFIT_BASE, s))
        elif re.fullmatch(r"[A-Za-z0-9\-_]{8,}", s):
            out.add(urljoin(SURFIT_BASE, f"/article/{s}"))

def extract_from_next_script(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.text:
        return []
    try:
        data = json.loads(tag.text)
    except Exception:
        return []
    acc = set(); walk_collect(data, acc)
    return list(acc)

def find_build_id(html: str):
    m = re.search(r'"buildId"\s*:\s*"([A-Za-z0-9\-_]+)"', html)
    if m: return m.group(1)
    m2 = re.search(r"/_next/data/([A-Za-z0-9\-_]+)/", html)
    return m2.group(1) if m2 else None

def route_to_data_path(route_url: str):
    parsed = urlparse(route_url)
    path = parsed.path or "/"
    q = ("?" + parsed.query) if parsed.query else ""
    if path in ("/", ""):
        return "/index.json" + q
    if not path.endswith(".json"):
        return f"{path}.json{q}"
    return path + q

def extract_via_next_data_api(html: str, route_url: str):
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
    acc = set(); walk_collect(data, acc)
    return list(acc)

def extract_article_urls_from_html(html: str, route_url: str):
    urls = set()
    # 1) 직접 노출 대비 정규식
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

# ---------- 사이트맵 시도(백업 플랜) ----------
def extract_from_sitemap(xml_text: str):
    # 가장 단순하고 강력한 방식: <loc>https://www.surfit.io/article/slug</loc>
    urls = re.findall(r"<loc>\s*(https?://www\.surfit\.io/article/[A-Za-z0-9\-_]+)\s*</loc>", xml_text)
    # 혹시 도메인에 www가 없는 경우도 수용
    urls += re.findall(r"<loc>\s*(https?://surfit\.io/article/[A-Za-z0-9\-_]+)\s*</loc>", xml_text)
    # 중복 제거
    uniq = []
    seen = set()
    for u in urls:
        u = u.strip()
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq

def discover_from_sitemaps():
    candidates = []
    for sm in SITEMAP_CANDIDATES:
        try:
            r = fetch(sm)
            print(f"[DEBUG] fetch sitemap {sm} -> {r.status_code}")
            if r.status_code == 200 and r.text:
                urls = extract_from_sitemap(r.text)
                print(f"[DEBUG]   found {len(urls)} article urls from sitemap")
                candidates.extend(urls)
        except Exception as e:
            print("[WARN] sitemap fetch error:", sm, e)
        time.sleep(0.3)
    # 사이트맵 인덱스일 경우(다른 sitemap 링크들) 재귀적으로도 가능하지만
    # 먼저 위 후보들로 충분히 잡히는지 확인
    # 필요 시 <sitemap><loc>…</loc></sitemap> 재귀 탐색 로직 추가 가능
    return candidates

# ---------- 메타/슬랙 ----------
def parse_meta(url: str):
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
        if desc: desc = " ".join(desc.split())[:280]
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
        if desc: text += f"\n{desc}"
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
    # 폴백
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

    # 1) 리스트 페이지 시도
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

    # 2) 리스트에서 0개면 사이트맵 시도
    if not candidates:
        print("[INFO] No urls from list pages. Trying sitemaps…")
        candidates = discover_from_sitemaps()

    # 중복 제거
    uniq, s = [], set()
    for u in candidates:
        if u not in s:
            s.add(u); uniq.append(u)

    new_urls = [u for u in uniq if article_id(u) not in seen]
    print(f"[DEBUG] total uniq: {len(uniq)}, new: {len(new_urls)}")

    send_urls = new_urls if new_urls else uniq[:5]
    if not send_urls:
        # 디버깅을 위해 HTML 일부 출력(로그상 1천자)
        try:
            test = fetch(LIST_PAGES[0])
            print("[DEBUG] first page sample:", (test.text[:1000].replace("\n"," ") if test.text else "NO HTML"))
        except Exception:
            pass
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
