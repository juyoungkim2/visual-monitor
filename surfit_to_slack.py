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
MAX_ITEMS = 8  # 한 번에 슬랙으로 보낼 개수(최대 8~10 추천)

def ensure_cache():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists():
        CACHE.write_text("[]", encoding="utf-8")

def fetch_html(url, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SurfitSlackBot/1.0",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"
    }
    return requests.get(url, headers=headers, timeout=timeout)

def parse_list(html):
    """리스트 페이지에서 /article/ 링크들 파싱"""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href*='/article/']"):
        href = a.get("href") or ""
        if "/article/" not in href:
            continue
        url = href if href.startswith("http") else urljoin(SURFIT_BASE, href)
        # 제목 추출(링크 텍스트 또는 하위 엘리먼트)
        title = " ".join((a.get_text(" ", strip=True) or "").split())
        if not title:
            # 카드 구조일 때 data- 속성 등 시도
            title = a.get("title") or ""
        if url and title:
            links.append((title, url))
    # 중복 제거, 최신이 위로 오도록 앞쪽 우선
    seen = set()
    out = []
    for t, u in links:
        if u in seen: continue
        seen.add(u); out.append((t, u))
    return out

def parse_meta_description(html):
    soup = BeautifulSoup(html, "html.parser")
    # og:description > meta description 순서
    og = soup.find("meta", attrs={"property":"og:description"})
    if og and og.get("content"): return og.get("content").strip()
    md = soup.find("meta", attrs={"name":"description"})
    if md and md.get("content"): return md.get("content").strip()
    # 본문 첫 문단 대용
    p = soup.find("p")
    if p: return " ".join(p.get_text(" ", strip=True).split())
    return ""

def load_seen():
    try:
        return set(json.loads(CACHE.read_text(encoding="utf-8")))
    except Exception:
        return set()

def save_seen(seen_set):
    CACHE.write_text(json.dumps(sorted(list(seen_set))[-500:],
                                ensure_ascii=False, indent=2), encoding="utf-8")

def article_id(url):
    # https://www.surfit.io/article/xxxxx 형태에서 id 추출
    m = re.search(r"/article/([A-Za-z0-9\-\_]+)", url)
    return m.group(1) if m else url

def pick_new_items(candidates, seen):
    new = []
    for title, url in candidates:
        aid = article_id(url)
        if aid not in seen:
            new.append((title, url, aid))
    return new

def build_slack_blocks(items):
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
    blocks = [{
        "type":"header",
        "text":{"type":"plain_text","text":f"🧩 Surfit 신규 아티클 - {today}"}
    }]
    sess = requests.Session()
    for title, url, _ in items[:MAX_ITEMS]:
        try:
            r = fetch_html(url, timeout=12)
            desc = parse_meta_description(r.text)[:280]
        except Exception:
            desc = ""
        text = f"*<{url}|{title}>*\n{desc}" if desc else f"*<{url}|{title}>*"
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":text}})
    return blocks

def post_to_slack(blocks):
    if not WEBHOOK:
        print("SLACK_WEBHOOK_URL not set")
        return False
    payload = {"text":"Surfit 신규 아티클", "blocks": blocks}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    print("Slack:", r.status_code, r.text[:200])
    return r.ok

def main():
    ensure_cache()
    seen = load_seen()

    # 1) 리스트 페이지들에서 후보 모으기
    candidates = []
    for lp in LIST_PAGES:
        try:
            res = fetch_html(lp)
            if res.status_code == 200:
                got = parse_list(res.text)
                candidates.extend(got)
        except Exception as e:
            print("list fetch error:", lp, e)
        time.sleep(0.5)

    # 2) 신규만 추리기 (보여준 적 없는 /article/ID)
    new_items = pick_new_items(candidates, seen)

    # 3) 없으면 상위 5개라도 보내기(최초 세팅 시 유용)
    if not new_items:
        print("No new items. Sending top picks for today.")
        # 상위 5개에 대해 임시 id 계산
        top = []
        for t,u in candidates[:5]:
            top.append((t,u,article_id(u)))
        blocks = build_slack_blocks(top)
        ok = post_to_slack(blocks)
        if ok:
            # 본문은 보내지 않지만, 캐시는 업데이트 안 함(진짜 신규만 캐시)
            pass
        return

    # 4) 슬랙 전송
    blocks = build_slack_blocks(new_items)
    ok = post_to_slack(blocks)

    # 5) 전송 성공 시 캐시 업데이트 후 저장
    if ok:
        for _, _, aid in new_items:
            seen.add(aid)
        save_seen(seen)

if __name__ == "__main__":
    main()
