import json, os, time, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# 📂 스크린샷 저장 경로 (날짜별 폴더)
OUT_DIR = Path("shots") / datetime.datetime.now().strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ✅ 드라이버 생성
def make_driver():
    opts = Options()
    if os.environ.get("CHROME_BIN"):
        opts.binary_location = os.environ["CHROME_BIN"]  # setup-chrome에서 설치된 Chrome 사용
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) KREAM-DesignBot")

    service = Service(ChromeDriverManager().install())  # 크롬 버전에 맞는 드라이버 자동 설치
    return webdriver.Chrome(service=service, options=opts)

def main():
    # 📄 모니터링 대상 URL 목록 불러오기
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)

    driver = make_driver()
    wait = WebDriverWait(driver, 10)

    for target in targets:
        url = target["url"]
        name = target["name"]
        driver.get(url)
        time.sleep(2)  # 페이지 로딩 대기
        screenshot_path = OUT_DIR / f"{name}.png"
        driver.save_screenshot(str(screenshot_path))
        print(f"📸 Saved screenshot: {screenshot_path}")

    driver.quit()

if __name__ == "__main__":
    main()
