"""AusTender contract notice collector.

Uses Selenium + Chrome to navigate the AusTender search form,
paginate all results, and return contracts above the min value.

Prerequisites:
  - chromedriver.exe at C:/Claude/kestrel/drivers/chromedriver.exe
  - Chrome at C:/Program Files/Google/Chrome/Application/chrome.exe
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
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
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.binary_location = CHROME_PATH
    service = Service(executable_path=DRIVER_PATH)
    drv = webdriver.Chrome(service=service, options=options)
    drv.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return drv


def _parse_value(text: str) -> Optional[int]:
    """Parse '$1,234,567.89' -> 1234567."""
    m = re.search(r"[\d,]+", text.replace("$", "").replace(" ", ""))
    if m:
        try:
            return int(m.group(0).replace(",", ""))
        except ValueError:
            pass
    return None


def _extract_boxes(driver: webdriver.Chrome) -> list[dict]:
    """Extract all listInner boxes from the current page."""
    boxes = driver.find_elements(By.CSS_SELECTOR, "div.listInner")
    results = []
    for box in boxes:
        data: dict = {}
        descs = box.find_elements(By.CSS_SELECTOR, "div.list-desc")
        for desc in descs:
            try:
                span = desc.find_element(By.TAG_NAME, "span")
                inner = desc.find_element(By.CSS_SELECTOR, "div.list-desc-inner")
                label = span.text.strip().rstrip(":")
                if label == "CN ID":
                    data["cn_id"] = inner.text.strip()
                    try:
                        link = inner.find_element(By.TAG_NAME, "a")
                        href = link.get_attribute("href") or ""
                        data["url"] = (
                            href if href.startswith("http") else BASE_URL + href
                        )
                    except Exception:
                        pass
                elif label == "Agency":
                    data["agency"] = inner.text.strip()
                elif label == "Publish Date":
                    data["publish_date"] = inner.text.strip()
                elif label == "Contract Value (AUD)":
                    data["value_text"] = inner.text.strip()
                    data["value"] = _parse_value(inner.text) or 0
                elif label == "Supplier Name":
                    data["supplier"] = inner.text.strip()
                elif label in ("Contact Name", "Contact Officer", "Contact Officer Name"):
                    data["contact_name"] = inner.text.strip()
                elif label in ("\xa0", ""):
                    # Full Details link carries the contract title in its title attr
                    try:
                        link = inner.find_element(By.CSS_SELECTOR, "a.detail")
                        title_attr = link.get_attribute("title") or ""
                        prefix = "Full Details for "
                        if title_attr.startswith(prefix):
                            data["title"] = title_attr[len(prefix):]
                    except Exception:
                        pass
            except Exception:
                pass
        if data.get("cn_id") and data.get("value", 0) > 0:
            results.append(data)
    return results


def _extract_contact_name(driver: webdriver.Chrome) -> str:
    """Read the 'Contact Name' value from a contract DETAIL page (Cn/Show/...).

    Detail-page markup is: <p><span>Contact Name:</span><br>VALUE</p>.
    The search listing does not expose this field, only the detail page does.
    """
    for p in driver.find_elements(
        By.XPATH, "//p[span[contains(normalize-space(.), 'Contact Name')]]"
    ):
        txt = (p.text or "").strip()
        if ":" in txt:
            val = txt.split(":", 1)[1].strip()
            if val:
                return val
    return ""


def fetch_contact_names(urls: list[str], timeout: int = 30) -> dict[str, str]:
    """Visit each contract detail page and return {url: contact_name}.

    Used to enrich only the final displayed selection (e.g. the top 10), since
    visiting every contract's detail page would be slow and wasteful.
    """
    if not urls or not Path(DRIVER_PATH).exists():
        return {}
    out: dict[str, str] = {}
    driver = None
    try:
        driver = _build_driver(timeout)
        for url in urls:
            try:
                driver.get(url)
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                name = _extract_contact_name(driver)
                if name:
                    out[url] = name
                    log.info("AusTender contact for %s: %s", url.rsplit("/", 1)[-1], name)
            except Exception as exc:
                log.warning("AusTender detail fetch failed for %s: %s", url, exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return out


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

        date_start = window.start.strftime("%d-%b-%Y")
        date_end = window.end.strftime("%d-%b-%Y")

        driver = None
        try:
            driver = _build_driver(self._timeout)

            # Step 1: submit the search form
            driver.get(f"{BASE_URL}/Cn/Search")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "form-dateType-PublishDate"))
            )
            driver.find_element(By.ID, "form-dateType-PublishDate").click()
            ds = driver.find_element(By.ID, "dateStart")
            ds.clear(); ds.send_keys(date_start)
            de = driver.find_element(By.ID, "dateEnd")
            de.clear(); de.send_keys(date_end)
            vf = driver.find_element(By.ID, "form-ValueFrom")
            vf.clear(); vf.send_keys(str(self._min_value))
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if "search" in btn.text.strip().lower():
                    btn.click()
                    break

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.listInner"))
            )

            # Step 2: collect page 1
            all_data = _extract_boxes(driver)
            log.info("AusTender page 1: %d contracts", len(all_data))

            # Step 3: paginate remaining pages via direct URL
            pagination = driver.find_elements(
                By.CSS_SELECTOR, ".pagination a[href*='page=']"
            )
            page_urls = {}
            for link in pagination:
                href = link.get_attribute("href") or ""
                m = re.search(r"page=(\d+)", href)
                if m:
                    page_urls[int(m.group(1))] = href

            for page_num in sorted(p for p in page_urls if p > 1):
                driver.get(page_urls[page_num])
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "div.listInner")
                        )
                    )
                    page_data = _extract_boxes(driver)
                    all_data.extend(page_data)
                    log.info("AusTender page %d: %d contracts", page_num, len(page_data))
                except Exception as exc:
                    log.warning("AusTender page %d error: %s", page_num, exc)

            # Build RawItems from collected data
            items = []
            for d in all_data:
                if d.get("value", 0) < self._min_value:
                    continue
                cn_id = d.get("cn_id", "")
                title = d.get("title") or f"Contract Notice {cn_id}"
                url = d.get("url") or f"{BASE_URL}/Cn/Show/{cn_id}"
                agency = d.get("agency", "")
                supplier = d.get("supplier", "")
                value = d.get("value", 0)
                value_text = d.get("value_text", "")
                snippet = f"[{cn_id}] {agency} | Supplier: {supplier} | Value: {value_text}"
                publish_date_str = d.get("publish_date", "")
                publish_date_iso = ""
                published_at = None
                if publish_date_str:
                    try:
                        dt = datetime.strptime(publish_date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
                        published_at = dt
                        publish_date_iso = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                items.append(RawItem(
                    title=title,
                    url=url,
                    source_name=source.name,
                    published_at=published_at,
                    snippet=snippet,
                    raw_meta={
                        "cn_id": cn_id,
                        "agency": agency,
                        "supplier": supplier,
                        "value": value,
                        "contact_name": d.get("contact_name", ""),
                        "publish_date": publish_date_iso,
                    },
                ))

            log.info(
                "AusTender -> %d contracts >= $%s", len(items), f"{self._min_value:,}"
            )
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
