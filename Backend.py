# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import csv
import time
from datetime import datetime
import re
import os
import random
import logging
from fake_useragent import UserAgent
import colorlog
import psycopg2
from psycopg2 import sql
from selenium.common.exceptions import TimeoutException, WebDriverException
import json
import urllib.parse

# Настройка цветного логирования
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'white',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler, logging.FileHandler("parser.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

# Базовый URL
BASE_URL = "https://market.yandex.ru/catalog--smartfony/26893750/list?hid=91491&page="

# Список известных брендов
KNOWN_BRANDS = {
    "samsung", "apple", "xiaomi", "realme", "oppo", "huawei", "honor", "oneplus",
    "poco", "blackview", "ulefone", "vivo", "nokia", "sony", "lg", "motorola",
    "infinix", "tecno", "asus", "zte", "nothing"
}

# Настройки подключения к PostgreSQL
DB_CONFIG = {
    "dbname": "Phones",
    "user": "postgres",
    "password": "12345",
    "host": "localhost",
    "port": "5432",
    "client_encoding": "UTF8"
}

# Селекторы для парсинга каталога
PRODUCT_CARD_SELECTORS = [
    "div[data-zone-name='snippet-card']",
    "div.n-snippet-card2",
    "div[data-apiary-widget*='snippet']",
    "article",
    "div.product-card",
]
TITLE_SELECTORS = [
    "h3[data-zone-name='title']",
    "span[data-auto='snippet-title']",
    "div[class*='title']",
    "span[class*='title']",
    "h3",
    "a[class*='title']",
]
LINK_SELECTORS = [
    "a[href*='/product--']",
    "a.n-snippet-card__link",
    "a[data-zone-name='link']",
    "a[href]",
]
PRICE_SELECTORS = [
    "span[data-auto='snippet-price-current']",
    "span[class*='price']",
    "div[class*='price']",
    "span[data-auto='price-value']",
]

# Селекторы для характеристик на странице товара
SPEC_LIST_SELECTORS = [
    "div._23gJ9",
    "div[data-zone-name='fullSpecs']",
    "div[data-auto='specs-list-fullExtended']",
    "div[class*='spec-list']",
    "div[data-zone-name='productSpecs']",
    "div[class*='specifications']",
    "div[data-auto='specifications']",
    "div[data-auto='specs-block']",
    "div[class*='product-characteristics']",
]

# Маппинг русских названий характеристик на английские поля
SPEC_MAPPING = {
    "диагональ": "screen_size",
    "диагональ экрана": "screen_size",
    "дисплей": "screen_size",
    "размер экрана": "screen_size",
    "разрешение экрана": "resolution",
    "разрешение дисплея": "resolution",
    "основная камера": "camera_mp",
    "камера": "camera_mp",
    "разрешение основной камеры": "camera_mp",
    "тыловая камера": "camera_mp",
    "емкость аккумулятора": "battery",
    "аккумулятор": "battery",
    "батарея": "battery",
    "процессор": "processor",
    "чип": "processor",
    "оперативная память": "ram",
    "встроенная память": "storage",
    "объем встроенной памяти": "storage",
    "память": "storage",
    "внутренняя память": "storage",
}

def setup_driver():
    ua = UserAgent()
    chrome_options = Options()
    chrome_options.add_argument(f"user-agent={ua.random}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--ignore-certificate-errors")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.navigator.chrome = {
                runtime: {},
            };
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3]
            });
        """
    })
    return driver


def clean_text(text):
    if not text:
        return ""
    text = text.replace(',', ' ').replace('\n', ' ').replace('\r', ' ')
    try:
        text = text.encode('utf-8').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            text = text.encode('utf-8').decode('windows-1251').encode('utf-8').decode('utf-8')
        except Exception as e:
            logger.warning(f"Ошибка кодировки в тексте: {str(e)}. Заменяем проблемные символы.")
            text = text.encode('utf-8', errors='replace').decode('utf-8')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_brand(name):
    if not name:
        return "Unknown"
    words = name.split()
    if not words:
        return "Unknown"
    skip_words = {"смартфон", "доставка", "глобальная", "[", "apple", "iphone", "телефон"}
    start_idx = 0
    for i, word in enumerate(words):
        if word.lower() in skip_words:
            start_idx = i + 1
        else:
            break
    if start_idx >= len(words):
        return "Unknown"
    candidate = words[start_idx].lower()
    if candidate in KNOWN_BRANDS:
        return words[start_idx]
    if "iphone" in name.lower():
        return "Apple"
    return words[start_idx] if start_idx < len(words) else "Unknown"


def dismiss_login_popup(driver):
    try:
        popup = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-apiary-widget-name='@light/LoginAgitationContent']"))
        )
        logger.debug("Обнаружен баннер авторизации")
        body = driver.find_element(By.TAG_NAME, "body")
        driver.execute_script("arguments[0].click();", body)
        logger.info("Баннер авторизации закрыт кликом по body")
        time.sleep(random.uniform(1, 2))
    except TimeoutException:
        logger.debug("Баннер авторизации не найден")


def hide_login_banner(driver):
    try:
        driver.execute_script("""
            var selectors = [
                'div[data-zone-name="floatingBanner"]',
                'div[class*="login-agitation"]',
                'div[data-apiary-widget-name="@light/LoginAgitationContent"]',
                'div[data-baobab-name="login_popup"]',
                'div[id*="marketfrontDynamicPopupLoader"]',
                'div[class*="ad-"]',
                'div[data-zone-name="banner"]'
            ];
            selectors.forEach(sel => {
                var elements = document.querySelectorAll(sel);
                elements.forEach(el => el.style.display = 'none');
            });
        """)
        logger.info("Баннеры и реклама скрыты через JavaScript")
    except Exception as e:
        logger.warning(f"Ошибка при скрытии баннеров: {str(e)}")


def scroll_page(driver):
    try:
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(random.uniform(1, 2))
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        logger.info("Прокрутка страницы завершена")
    except Exception as e:
        logger.warning(f"Ошибка при прокрутке страницы: {str(e)}")


def get_html(url, driver, retries=3):
    for attempt in range(retries):
        try:
            logger.info(f"Загружаем (попытка {attempt + 1}): {url}")
            driver.get(url)
            dismiss_login_popup(driver)
            hide_login_banner(driver)

            if "showcaptcha" in driver.current_url.lower() or "Капча" in driver.title:
                logger.warning("Обнаружена капча! Перезагружаем страницу...")
                time.sleep(random.uniform(1, 3))
                driver.refresh()

            if "catalog" in url.lower():
                wait_condition = lambda d: any(d.find_elements(By.CSS_SELECTOR, sel) for sel in PRODUCT_CARD_SELECTORS) or \
                    d.find_elements(By.CSS_SELECTOR, "div[data-zone-name='emptyState']")
            else:
                wait_condition = lambda d: any(d.find_elements(By.CSS_SELECTOR, sel) for sel in SPEC_LIST_SELECTORS)

            WebDriverWait(driver, 30).until(wait_condition)

            empty_state = driver.find_elements(By.CSS_SELECTOR, "div[data-zone-name='emptyState']")
            if empty_state:
                logger.info("Пустая страница - конец каталога")
                return None

            if "Доступ ограничен" in driver.title or "доступ к сайту" in driver.page_source.lower():
                logger.error("Доступ к сайту ограничен")
                raise Exception("Доступ к сайту ограничен")

            scroll_page(driver)
            html = driver.page_source

            if len(html) < 5000:
                logger.warning("Слишком короткий HTML-код страницы")
                raise Exception("Слишком короткий HTML-код страницы")

            logger.info(f"HTML загружен, длина: {len(html)} символов")
            return html
        except (TimeoutException, WebDriverException) as e:
            logger.error(f"Ошибка при загрузке {url} (попытка {attempt + 1}): {str(e)[:200]}")
            if attempt == retries - 1:
                logger.error("Все попытки исчерпаны")
                try:
                    with open(f"error_page_{url.split('=')[-1]}_{attempt}.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info(f"Сохранен HTML ошибки в error_page_{url.split('=')[-1]}_{attempt}.html")
                except Exception as save_e:
                    logger.error(f"Ошибка при сохранении HTML ошибки: {save_e}")
                return None
            time.sleep(random.uniform(5, 10))
    return None


def click_full_specs_button(driver):
    for attempt in range(3):
        try:
            full_specs_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Все характеристики')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", full_specs_button)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", full_specs_button)
            logger.info("Клик по кнопке 'Все характеристики'")
            time.sleep(random.uniform(5, 8))
            return True
        except Exception as e:
            logger.debug(f"Попытка {attempt + 1} клика по кнопке 'Все характеристики' не удалась: {str(e)}")
    return False


def extract_specs_from_json(html):
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    specs = {}
    for script in scripts:
        if not script.string:
            continue
        if any(keyword in script.string.lower() for keyword in [
            "productspecs", "specifications", "productcard", "props", "collections", "spec", "params", "characteristics"
        ]):
            try:
                json_matches = re.finditer(r'({[^{}]*?(?:"specifications"|"props"|"collections"|"params")[^{}]*})', script.string, re.DOTALL)
                for match in json_matches:
                    data = json.loads(match.group(1))
                    def extract_recursive(obj):
                        if isinstance(obj, dict):
                            for key, value in obj.items():
                                if key.lower() in ["specifications", "specs", "productspecs", "props", "params"]:
                                    if isinstance(value, list):
                                        for item in value:
                                            if isinstance(item, dict):
                                                k = clean_text(item.get("name") or item.get("title") or item.get("key", "")).lower()
                                                v = clean_text(item.get("value") or item.get("content") or item.get("val", ""))
                                                if k and v:
                                                    specs[k] = v
                                    elif isinstance(value, dict):
                                        for k, v in value.items():
                                            k = clean_text(k).lower()
                                            v = clean_text(str(v))
                                            if k and v:
                                                specs[k] = v
                                elif key.lower() == "collections":
                                    if isinstance(value, dict):
                                        for coll_key, coll_val in value.items():
                                            if isinstance(coll_val, dict) and "spec" in coll_key.lower():
                                                for spec_key, spec_val in coll_val.items():
                                                    k = clean_text(spec_key).lower()
                                                    v = clean_text(str(spec_val))
                                                    if k and v:
                                                        specs[k] = v
                                extract_recursive(value)
                        elif isinstance(obj, list):
                            for item in obj:
                                extract_recursive(item)
                    extract_recursive(data)
            except Exception as e:
                logger.debug(f"Ошибка при обработке JSON: {str(e)}")
    return specs


def parse_product_page(url, driver):
    html = get_html(url, driver)
    if not html:
        logger.warning(f"Не удалось загрузить страницу товара: {url}")
        return {}

    click_full_specs_button(driver)
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    # Парсинг из DOM
    dom_specs = {}
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) >= 2:
                key = clean_text(cols[0].get_text(strip=True)).lower()
                val = clean_text(cols[1].get_text(strip=True))
                if key and val:
                    dom_specs[key] = val

    # Парсинг из JSON
    json_specs = extract_specs_from_json(html)

    combined_specs = {**dom_specs, **json_specs}
    if not combined_specs:
        logger.warning(f"Не удалось извлечь характеристики для {url}")

    specs = {
        "screen_size": None,
        "resolution": None,
        "camera_mp": None,
        "battery": None,
        "processor": None,
        "ram": None,
        "storage": None,
    }

    for key, value in combined_specs.items():
        mapped_key = None
        for ru_key, en_key in SPEC_MAPPING.items():
            if ru_key in key:
                mapped_key = en_key
                break
        if not mapped_key or mapped_key not in specs:
            continue

        try:
            if mapped_key == "screen_size":
                match = re.search(r"([\d.]+(?:–[\d.]+)?)(?=\s*дюйм)", value)
                if match:
                    val = match.group(1).split("–")[0]
                    specs[mapped_key] = float(val)

            elif mapped_key == "resolution":
                match = re.search(r"(\d+x\d+)", value)
                specs[mapped_key] = match.group() if match else value

            elif mapped_key in ["camera_mp", "battery", "ram", "storage"]:
                match = re.search(r"(\d+)", value)
                specs[mapped_key] = int(match.group()) if match else None

            elif mapped_key == "processor":
                specs[mapped_key] = value.strip()

        except Exception as e:
            logger.warning(f"Ошибка преобразования {key}={value}: {e}")
            continue

    logger.info(f"Характеристики извлечены: {specs}")
    return specs


def setup_database():
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SET client_encoding TO 'UTF8';")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                brand TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                price INTEGER NOT NULL,
                last_updated TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                CONSTRAINT fk_prices_product FOREIGN KEY (product_id) REFERENCES products(id),
                CONSTRAINT fk_prices_store FOREIGN KEY (store_id) REFERENCES stores(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                price INTEGER NOT NULL,
                recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                CONSTRAINT fk_price_history_product FOREIGN KEY (product_id) REFERENCES products(id),
                CONSTRAINT fk_price_history_store FOREIGN KEY (store_id) REFERENCES stores(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_specs (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                screen_size DOUBLE PRECISION,
                resolution TEXT,
                camera_mp INTEGER,
                battery INTEGER,
                processor TEXT,
                ram INTEGER,
                storage INTEGER,
                CONSTRAINT fk_product_specs_product FOREIGN KEY (product_id) REFERENCES products(id),
                CONSTRAINT unique_product_id UNIQUE (product_id)
            );
        """)
        conn.commit()
        logger.info("Таблицы успешно созданы или уже существуют.")
    except Exception as e:
        logger.error(f"Ошибка при создании таблиц: {str(e)}")
    finally:
        if conn:
            cursor.close()
            conn.close()


def save_to_database(products):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SET client_encoding TO 'UTF8';")
        store_name = "Yandex.Market"
        store_url = "https://market.yandex.ru"

        cursor.execute("SELECT id FROM stores WHERE name = %s", (store_name,))
        store = cursor.fetchone()
        if not store:
            cursor.execute("INSERT INTO stores (name, url) VALUES (%s, %s) RETURNING id", (store_name, store_url))
            store_id = cursor.fetchone()[0]
        else:
            store_id = store[0]

        products_added = 0
        prices_added = 0
        price_history_added = 0
        specs_added = 0
        specs_updated = 0

        for product in products:
            if not product.get("name") or not product.get("brand"):
                logger.warning("Пропущен продукт: отсутствует название или бренд")
                continue

            cursor.execute("SELECT id FROM products WHERE name = %s AND brand = %s", (product["name"], product["brand"]))
            existing_product = cursor.fetchone()

            if existing_product:
                product_id = existing_product[0]
            else:
                cursor.execute(
                    "INSERT INTO products (name, brand, category, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
                    (product["name"], product["brand"], product["category"], product["last_updated"])
                )
                product_id = cursor.fetchone()[0]
                products_added += 1

            cursor.execute(
                "INSERT INTO price_history (product_id, store_id, price, recorded_at) VALUES (%s, %s, %s, %s)",
                (product_id, store_id, product["price"], product["last_updated"])
            )
            price_history_added += 1

            cursor.execute("SELECT id FROM prices WHERE product_id = %s AND store_id = %s", (product_id, store_id))
            existing_price = cursor.fetchone()

            if existing_price:
                cursor.execute(
                    "UPDATE prices SET price = %s, last_updated = %s WHERE id = %s",
                    (product["price"], product["last_updated"], existing_price[0])
                )
            else:
                cursor.execute(
                    "INSERT INTO prices (product_id, store_id, price, last_updated) VALUES (%s, %s, %s, %s)",
                    (product_id, store_id, product["price"], product["last_updated"])
                )
            prices_added += 1

            specs_dict = product.get("specifications", {})
            if specs_dict and any(val is not None for val in specs_dict.values()):
                cursor.execute("SELECT id FROM product_specs WHERE product_id = %s", (product_id,))
                existing_specs = cursor.fetchone()

                if existing_specs:
                    cursor.execute(
                        """
                        UPDATE product_specs
                        SET screen_size = %s, resolution = %s, camera_mp = %s,
                            battery = %s, processor = %s, ram = %s, storage = %s
                        WHERE product_id = %s
                        """,
                        (
                            specs_dict["screen_size"],
                            specs_dict["resolution"],
                            specs_dict["camera_mp"],
                            specs_dict["battery"],
                            specs_dict["processor"],
                            specs_dict["ram"],
                            specs_dict["storage"],
                            product_id
                        )
                    )
                    specs_updated += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO product_specs (product_id, screen_size, resolution, camera_mp,
                                                  battery, processor, ram, storage)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            product_id,
                            specs_dict["screen_size"],
                            specs_dict["resolution"],
                            specs_dict["camera_mp"],
                            specs_dict["battery"],
                            specs_dict["processor"],
                            specs_dict["ram"],
                            specs_dict["storage"]
                        )
                    )
                    specs_added += 1
            else:
                logger.warning(f"Пропущено сохранение спецификаций для продукта {product['name']} (ID: {product_id}): характеристики пустые")

        conn.commit()
        logger.info(f"Сохранено {products_added} новых продуктов, {prices_added} цен, "
                    f"{price_history_added} записей в истории цен, {specs_added} новых спецификаций, "
                    f"{specs_updated} спецификаций обновлено")
    except Exception as e:
        logger.error(f"Ошибка при сохранении в базу данных: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()


def parse_catalog(page, driver):
    url = f"{BASE_URL}{page}"
    html = get_html(url, driver)
    if not html:
        logger.info("Пустая страница")
        return []
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for card_selector in PRODUCT_CARD_SELECTORS:
        items = soup.select(card_selector)
        if items:
            logger.info(f"Найдено {len(items)} карточек товаров с селектором: {card_selector}")
            break
    else:
        logger.error(f"Не найдено карточек товаров на странице {page} с любым селектором")
        return []

    for idx, item in enumerate(items):
        name_tag = None
        for title_selector in TITLE_SELECTORS:
            name_tag = item.select_one(title_selector)
            if name_tag:
                break
        if not name_tag:
            continue

        link_tag = None
        for link_selector in LINK_SELECTORS:
            link_tag = item.select_one(link_selector)
            if link_tag:
                break
        if not link_tag:
            continue

        price_tag = None
        for price_selector in PRICE_SELECTORS:
            price_tag = item.select_one(price_selector)
            if price_tag:
                break
        if not price_tag:
            continue

        name = clean_text(name_tag.text)
        if not name:
            continue

        link = "https://market.yandex.ru"  + link_tag["href"] if link_tag["href"].startswith("/") else link_tag["href"]
        price_text = re.sub(r"[^\d]", "", price_tag.text.strip()) if price_tag else ""
        brand = extract_brand(name)

        if not price_text or not price_text.isdigit():
            continue

        try:
            price = int(price_text)
        except ValueError:
            continue

        product = {
            "name": name,
            "brand": brand,
            "category": "Smartphone",
            "price": price,
            "store": "Yandex.Market",
            "link": link,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        products.append(product)

    logger.info(f"После фильтрации найдено {len(products)} товаров на странице {page}")
    return products


def main(max_pages=1):
    driver = setup_driver()
    all_products = []
    setup_database()
    try:
        for page in range(1, max_pages + 1):
            if page % 5 == 0:
                driver.quit()
                driver = setup_driver()
                logger.info("Драйвер перезапущен для смены User-Agent")
            logger.info(f"\nПарсим страницу {page} из {max_pages}...")
            products = parse_catalog(page, driver)
            if not products:
                logger.info(f"Нет товаров на странице {page}. Пропускаем.")
                continue
            for i, product in enumerate(products, 1):
                logger.info(f"Обрабатываем товар {i}/{len(products)}: {product['name']}")
                specs = parse_product_page(product["link"], driver)
                product["specifications"] = specs
                all_products.append(product)
                time.sleep(random.uniform(2, 5))
        if not all_products:
            logger.error("Нет данных для сохранения!")
            return
        save_to_database(all_products)
        logger.info(f"Парсинг завершен! Обработано {len(all_products)} товаров.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
    finally:
        driver.quit()
        logger.info("Драйвер закрыт.")


if __name__ == "__main__":
    main(max_pages=1)