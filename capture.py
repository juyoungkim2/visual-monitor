import json, os, time, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 날짜별 폴더에 저장
OUT_DIR = Path("shots") / datetime.datetime.now().strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def make_driver():
    opts = Options()
    if os.environ.get("CHROME_BIN"):
        opts.binary_location = os.environ["CHROME_BIN"]  # setup-chrome 경로
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) KREAM-DesignBot")
    # Selenium Manager가 알아서 맞는 드라이버 받아서 사용
    return webdriver.Chrome(options=opts)

def main():
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)

    d = make_driver()
    # 디버그: 버전 찍기
    try:
        caps = d.capabilities
        print("[Chrome ]", caps.get("browserVersion"))
        print("[Driver ]", (caps.get("chrome", {}) \
              .get("chromedriverVersion","")).split(" ")[0])
    except Exception: pass

    for t in targets:
        name, url = t["name"], t["url"]
        try:
            d.get(url)
            time.sleep(2.0)  # 간단 대기
            fp = OUT_DIR / f"{name}.png"
            d.save_screenshot(str(fp))
            print("Captured:", fp)
        except Exception as e:
            print("Capture error:", name, e)

    d.quit()

if __name__ == "__main__":
    main()
