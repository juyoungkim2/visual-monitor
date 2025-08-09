import json, os, time, datetime
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service          # Selenium Manager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 저장 폴더: shots/YYYY-MM-DD
OUT_DIR = Path("shots") / datetime.datetime.now().strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------- Selenium helpers --------
def make_driver() -> webdriver.Chrome:
    opts = Options()
    if os.environ.get("CHROME_BIN"):
        opts.binary_location = os.environ["CHROME_BIN"]
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) KREAM-DesignBot")

    # 경로 미지정 Service() → Selenium Manager가 현재 Chrome에 맞는 드라이버 자동 설치/사용
    service = Service()
    return webdriver.Chrome(service=service, options=opts)

def _wait_click(driver: webdriver.Chrome, by: By, value: str, timeout: int = 6) -> bool:
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, value)))
        el.click()
        return True
    except Exception:
        return False

def click_any(driver: webdriver.Chrome, selectors: List[Tuple[str, str]], timeout: int = 6) -> bool:
    """
    selectors 예:
      [["css","a[href*='kr.musinsa.com']"], ["link_text","Korea"], ["xpath","//a[contains(.,'대한민국')]"]]
    """
    for kind, val in selectors:
        kind = kind.lower()
        if kind == "css":
            if _wait_click(driver, By.CSS_SELECTOR, val, timeout): return True
        elif kind == "xpath":
            if _wait_click(driver, By.XPATH, val, timeout): return True
        elif kind == "link_text":
            if _wait_click(driver, By.LINK_TEXT, val, timeout): return True
        elif kind == "partial_text":
            if _wait_click(driver, By.PARTIAL_LINK_TEXT, val, timeout): return True
    return False

def run_actions(driver: webdriver.Chrome, actions: list | None):
    if not actions: return
    for act in actions:
        typ = (act.get("type") or "").lower()
        if typ == "click_any":
            sels = act.get("selectors") or []
            timeout = int(act.get("timeout", 6))
            ok = click_any(driver, sels, timeout)
            print(f"[action] click_any -> {ok}")
        elif typ == "sleep":
            time.sleep(float(act.get("seconds", 1.0)))
        elif typ == "wait":
            sel = act.get("selector", "body")
            timeout = int(act.get("timeout", 8))
            try:
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
            except Exception:
                print(f"[action] wait timeout: {sel}")

# -------- main flow --------
def main():
    # 매 실행 시 오늘 폴더의 잔여 PNG 제거
    for p in OUT_DIR.glob("*.png"):
        try: p.unlink()
        except: pass

    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)

    d = make_driver()

    # 디버그: 버전 로그
    try:
        caps = d.capabilities
        print("[Chrome ]", caps.get("browserVersion"))
        drv = (caps.get("chrome", {}) or {}).get("chromedriverVersion", "")
        print("[Driver ]", drv.split(" ")[0])
    except Exception:
        pass

    for t in targets:
        name = t["name"]
        url  = t["url"]
        wait_selector = t.get("wait_selector", "body")
        actions = t.get("actions", [])

        try:
            print(f"\n=== {name} ===")
            d.get(url)
            # 사이트별 액션(지역 선택/쿠키 동의 등)
            run_actions(d, actions)

            # 최종 대기 후 스크린샷
            try:
                WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector)))
            except Exception:
                print(f"[warn] wait_selector not found: {wait_selector}")

            time.sleep(1.0)
            out = OUT_DIR / f"{name}.png"
            d.save_screenshot(str(out))
            print("Captured:", out)
        except Exception as e:
            print("Capture error:", name, e)

    d.quit()

if __name__ == "__main__":
    main()
