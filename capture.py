import json, os, time, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT_DIR = Path("shots") / datetime.datetime.now().strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def make_driver():
    opts = Options()
    if os.environ.get("CHROME_BIN"):
        opts.binary_location = os.environ["CHROME_BIN"]
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) KREAM-DesignBot")
    return webdriver.Chrome(options=opts)   # ← PATH에 깔린 맞춤 드라이버 사용

def main():
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)

    driver = make_driver()

    for t in targets:
        try:
            driver.get(t["url"])
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, t["wait_selector"]))
            )
            time.sleep(1)
            file_path = OUT_DIR / f"{t['name']}.png"
            driver.save_screenshot(str(file_path))
            print(f"Captured: {file_path}")
        except Exception as e:
            print(f"Error capturing {t['name']}: {e}")

    driver.quit()

if __name__ == "__main__":
    main()
