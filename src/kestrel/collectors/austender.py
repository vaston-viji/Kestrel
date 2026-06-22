"""AusTender contract notice collector.

Uses Selenium + Chrome to render the JavaScript-heavy AusTender search page
and extract contract notices > $1M published within the lookback window.

Prerequisites:
  - chromedriver.exe at C:/Claude/kestrel/drivers/chromedriver.exe
  - Chrome at C:/Program Files/Google/Chrome/Application/chrome.exe
"""
from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from kestrel.models import RawItem, Source, Window

log = logging.getLogger(__name__)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DRIVER_PATH = str(Path(__file__).parents[3] / "drivers" / "chromedriver.exe")
BASE_URL = "https://www.tenders.gov.au"
MIN_VALUE = 1_000_000


def _build_driver(timeout: int = 20) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.binary_location = CHROME_PATH
    service = Service(executable_path=DRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)


def _parse_value(text: str) -> Optional[int]:
    """Parse '$1,234,567' -> 1234567."""
    m = re.search(r"[\d,]+", text.replace("$", "").replace(" ", ""))
    if m:
        try:
            return int(m.group(0).replace(",", ""))
        except ValueError:
            pass
    return None


class AusTenderCollector:
    def __init__(self, timeout: int = 45, min_value: int = MIN_VALUE) -> None:
        self._timeout = timeout
        self._min_value = min_value

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        if not Path(DRIVER_PATH).exists():
            log.warning(
                "ChromeDriver not found at %s — run handover/download_chromedriver.py",
                DRIVER_PATH,
            )
            return []

        date_start = window.start.strftime("%Y-%m-%d")
        date_end = window.end.strftime("%Y-%m-%d")
        url = (
            f"{BASE_URL}/Cn/Search"
            f"?dateType=Publish+Date"
            f"&dateStart={date_start}"
            f"&dateEnd={date_end}"
            f"&ValueFrom={self._min_value}"
        )

        driver = None
        try:
            driver = _build_driver(self._timeout)
            driver.get(url)

            wait = WebDriverWait(driver, 15)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.results tbody tr")))
            except Exception:
                log.warning("AusTender: results table not found within timeout for %s", url)
                return []

            rows = driver.find_elements(By.CSS_SELECTOR, "table.results tbody tr")
            items = []
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 5:
                        continue
                    cn_id = cells[0].text.strip()
                    title = cells[1].text.strip()
                    agency = cells[2].text.strip()
                    supplier = cells[3].text.strip()
                    value_text = cells[4].text.strip()
                    value = _parse_value(value_text)

                    if value is not None and value < self._min_value:
                        continue

                    link_el = cells[1].find_elements(By.TAG_NAME, "a")
                    href = link_el[0].get_attribute("href") if link_el else ""
                    if href and not href.startswith("http"):
                        href = BASE_URL + href

                    snippet = f"[{cn_id}] {agency} | Supplier: {supplier} | Value: {value_text}"

                    items.append(RawItem(
                        title=title or f"Contract Notice {cn_id}",
                        url=href or f"{BASE_URL}/Cn/View/{cn_id}",
                        source_name=source.name,
                        published_at=None,
                        snippet=snippet,
                        raw_meta={
                            "cn_id": cn_id,
                            "agency": agency,
                            "supplier": supplier,
                            "value": value,
                        },
                    ))

                except Exception as exc:
                    log.debug("AusTender row parse error: %s", exc)

            log.info("AusTender -> %d contracts > $%s", len(items), f"{self._min_value:,}")
            return items

        except Exception as exc:
            log.warning("AusTender collector error: %s", exc)
            return []
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
