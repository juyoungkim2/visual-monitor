import json, os, time, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

OUT_DIR = Path("shots") / datetime.datetime.now().strftime("%Y-%m-%d")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def make_driver():
    opts = Options()
    if os.environ.get("CHROME_BIN"):
        opts.binary_location = os.environ["CHROME_BIN"]  # setup-chrome가 깔아준 Chrome 쓰기
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) KREAM-DesignBot")

    # ✅ 크롬 버전에 맞는 chromedriver를 자동 설치/사용
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)

def fullshot(d, path):
  h = d.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);")
  d.set_window_size(1440, min(h, 4000)); time.sleep(0.8); d.save_screenshot(path)

def shot_elem(d, selector, path):
  try:
    el = WebDriverWait(d, 6).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.5); el.screenshot(path); return True
  except: return False

def main():
  with open("targets.json", encoding="utf-8") as f: targets = json.load(f)
  d = make_driver(); out = []
  for t in targets:
    name, url, sel = t["name"], t["url"], t.get("selector")
    try:
      d.get(url)
      WebDriverWait(d, 8).until(lambda x: x.execute_script("return document.readyState")== "complete")
      time.sleep(1.2)
      fn = f"{name.replace(' ','_')}.png"; path = OUT_DIR / fn
      ok = shot_elem(d, sel, str(path)) if sel else False
      if not ok: fullshot(d, str(path))
      out.append({"name":name, "path":str(path).replace('\\','/'), "url":url})
    except Exception as e:
      print("ERR", name, e)
  d.quit()
  with open(OUT_DIR / "_index.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__": main()
