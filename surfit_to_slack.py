import os, json, time, re
import datetime as dt
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

SURFIT_BASE = "https://www.surfit.io"
LIST_PAGES = [
    "https://www.surfit.io/",
    "https://www.surfit.io/discover",
]
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
CACHE = Path(".cache/surfit_seen.json")

MAX_ITEMS = 8         # 한 번에 전송할 개수
FETCH_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SurfitSlackBot/1.1",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def ensure_cache():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        CACHE.write_text("[]", encoding="utf-8")

def fetch(url):
    return requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)

def article_id(url: str) -> str:
    m = re.search(r"/article/([A-Za-z0-9\-_]+)", url)
    return m.group(1) if m else url

def load_seen():
    try:
        return set(json.loads(CACHE.read_text(encoding="utf-8")))
    except Exception:
        return set()

def save_seen(seen):
    # 최근 500개만 유지
    CACHE.write_text(json.dumps(sorted(list(seen))[-500:],
                                ensure_ascii=False, indent=2), encoding="utf-8")

def extract_article_urls_from_html(html: str):
    """
    JS 렌더링 없이 원문 문자열에서 /article/ 링크를 정규식으로 수집
    절대/상대 경로 모두 처리
    """
    urls = set()

    # 1) 절대 경로
    for u in re.findall(r"https?://www\.surfit\.io/article/[A-Za-z0-9\-_]+", html):
        urls.add(u)

    # 2) 상대 경로
    for u in re.findall(r'"(/article/[A-Za-z0-9\-_]+)"', html):
        urls.add(urljoin(SURFIT_BASE, u))

    return list(urls)

def parse_meta(url: str):
    """
    개별 글 페이지에서 og:title / og:description을 읽어 슬랙용 텍스트를 만든다.
    """
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

def build_blocks(items):
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
    blocks = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"🧩 Surfit 신규 아티클 - {today}"}
    }]

    for url in items[:MAX_ITEMS]:
        title, desc = parse_meta(url)
        # 제목이 없으면 URL에서라도 아이디를 제목처럼 보여주자
        if not title:
            title = f"Surfit Article {article_id(url)}"
        if desc:
            text = f"*<{url}|{title}>*\n{desc}"
        else:
            text = f"*<{url}|{title}>*"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    return blocks

def post_to_slack(blocks):
    if not WEBHOOK:
        print("SLACK_WEBHOOK_URL not set")
        return False
    payload = {"text": "Surfit 신규 아티클", "blocks": blocks}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    print("Slack:", r.status_code, r.text[:200])
    return r.ok

def main():
    ensure_cache()
    seen = load_seen()

    # 1) 리스트 페이지에서 원문 문자열을 가져와 링크 수집
    candidates = []
    for page in LIST_PAGES:
        try:
            res = fetch(page)
            if res.status_code == 200 and res.text:
                urls = extract_article_urls_from_html(res.text)
                candidates.extend(urls)
        except Exception as e:
            print("fetch error:", page, e)
        time.sleep(0.5)

    # 중복 제거 및 최신 우선(앞쪽 유지)
    uniq = []
    s = set()
    for u in candidates:
        if u not in s:
            s.add(u)
            uniq.append(u)

    # 2) 신규만 필터
    new_urls = [u for u in uniq if article_id(u) not in seen]

    # 3) 신규 없으면 상위 5개라도 전송(초기 세팅 확인용)
    send_urls = new_urls if new_urls else uniq[:5]
    if not send_urls:
        print("No article URLs found on list pages.")
        return

    blocks = build_blocks(send_urls)
    ok = post_to_slack(blocks)

    if ok:
        for u in new_urls:
            seen.add(article_id(u))
        save_seen(seen)

if __name__ == "__main__":
    main()
