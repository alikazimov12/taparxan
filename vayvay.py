#!/usr/bin/env python3
import asyncio
import json
import datetime
import random
import time
import itertools
from typing import Optional

from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

# cloudscraper is used to bypass Cloudflare JS challenges
import cloudscraper
import requests  # used only for exceptions typing maybe

# ---------------- CONFIG ----------------
TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"  # <-- buraya token qoy
SUBSCRIBERS_FILE = "subscribers.json"
BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"

# Optional proxy list (http format). Əgər proxy istəmirsənsə boş saxla.
PROXIES = [
    # "http://user:pass@1.2.3.4:8080",
    # "http://167.86.74.155:21966",
]

# UA rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
]

# runtime behavior
PAGES_TO_SCRAPE = 3
CHECK_INTERVAL = 60  # seconds between cycles (1 hour). Test üçün azalda bilərsən.
MIN_DELAY = 1.0
MAX_DELAY = 2.0
REQUEST_TIMEOUT = 20

# ---------------- global state ----------------
bot = Bot(token=TOKEN)
dp = Dispatcher()

subscribers = set()
seen_urls = set()         # runtime-da hansı elanlar göndərilib (yenidən göndərməmək üçün)
START_TIME = datetime.datetime.now()
print(f"[DEBUG] Bot start vaxtı: {START_TIME.isoformat()}")

# cloudscraper session yarat (Cloudflare bypass)
SCRAPER = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)

# proxy cycle
proxy_cycle = itertools.cycle(PROXIES) if PROXIES else None


# ---------------- helpers ----------------
def load_subscribers():
    global subscribers
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            subscribers = set(json.load(f))
            print(f"[DEBUG] Loaded {len(subscribers)} subscribers.")
    except FileNotFoundError:
        subscribers = set()
    except Exception as e:
        print(f"[DEBUG] Failed loading subscribers: {e}")
        subscribers = set()


def save_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(list(subscribers), f)
    except Exception as e:
        print(f"[DEBUG] Failed saving subscribers: {e}")


def next_proxy() -> Optional[str]:
    if not proxy_cycle:
        return None
    return next(proxy_cycle)


def get_headers() -> dict:
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "az,en-US;q=0.9,en;q=0.8",
        "Referer": "https://tap.az/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def detect_cloudflare_body(text: str) -> bool:
    t = (text or "").lower()
    return ("cf-browser-verification" in t) or ("attention required!" in t) or ("cloudflare" in t and "check" in t)


# Blocking network call but wrapped with cloudscraper; we'll call it via asyncio.to_thread
def blocking_request(url: str, params: dict = None, proxy: Optional[str] = None):
    headers = get_headers()
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    # polite small sleep to avoid rapid-fire pattern
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    print(f"[DEBUG] Requesting {url} proxy={proxy} UA={headers['User-Agent']}")
    resp = SCRAPER.get(url, headers=headers, params=params, proxies=proxies, timeout=REQUEST_TIMEOUT)
    # detect cloudflare in body
    if detect_cloudflare_body(resp.text):
        raise RuntimeError("Cloudflare challenge detected in response body")
    resp.raise_for_status()
    return resp


# check ad page if shop button exists (blocking, use in thread)
def blocking_is_shop_ad(ad_url: str, proxy: Optional[str] = None) -> bool:
    try:
        r = blocking_request(ad_url, proxy=proxy)
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.select_one('a[data-stat="shop-ad-go-shop-btn"]')
        if el:
            print(f"[DEBUG] Mağaza elanı tapıldı: {ad_url}")
            return True
    except Exception as e:
        # on error, print and return False (we choose to include ad if check fails)
        print(f"[DEBUG] is_shop_ad error for {ad_url}: {e}")
        return False
    return False


# fetch a single listing page, return ads list and next cursor
def blocking_fetch_page(cursor: Optional[str] = None):
    params = {"keywords_source": "typewritten", "order": "newest"}
    if cursor:
        params["cursor"] = cursor

    proxy = next_proxy() if proxy_cycle else None

    try:
        resp = blocking_request(BASE_URL, params=params, proxy=proxy)
    except Exception as e:
        print(f"[ERROR] Failed to fetch listing page: {e}")
        return [], None

    soup = BeautifulSoup(resp.text, "html.parser")
    ads = []

    for card in soup.select(".products-i"):
        # listing-level quick skip
        if "products-shop" in (card.get("class") or []):
            print("[DEBUG] Skip card with products-shop class (listing-level).")
            continue

        date_tag = card.select_one(".products-created")
        if not date_tag:
            continue
        date_text = date_tag.text.strip().lower()  # e.g. "bakı, bugün, 16:19"
        if "bugün" not in date_text:
            continue

        # parse time part
        try:
            time_part = date_text.split(",")[-1].strip()
            t = datetime.datetime.strptime(time_part, "%H:%M").time()
            ad_dt = datetime.datetime.combine(START_TIME.date(), t)
        except Exception:
            continue

        if ad_dt < START_TIME:
            # posted before bot start
            continue

        link_tag = card.select_one("a[href]")
        if not link_tag:
            continue
        href = link_tag.get("href")
        if not href:
            continue
        ad_url = "https://tap.az" + href

        # check inside ad page for shop button (blocking)
        proxy_for_ad = next_proxy() if proxy_cycle else None
        if blocking_is_shop_ad(ad_url, proxy=proxy_for_ad):
            continue

        title = (card.select_one(".products-name").get_text(strip=True)
                 if card.select_one(".products-name") else "No title")
        price = (card.select_one(".products-price .price-val").get_text(strip=True)
                 if card.select_one(".products-price .price-val") else "No price")

        ads.append({"title": title, "price": price, "url": ad_url})

    # try to extract cursor from response final url
    new_cursor = None
    try:
        final_url = resp.url
        if "cursor=" in final_url:
            new_cursor = final_url.split("cursor=")[-1]
    except Exception:
        new_cursor = None

    print(f"[DEBUG] Fetched page, {len(ads)} elan tapıldı")
    return ads, new_cursor


# synchronous scrape_all wrapper (will be called inside a thread)
def blocking_scrape_all(pages: int = PAGES_TO_SCRAPE):
    all_ads = []
    cursor = None
    for i in range(pages):
        ads, cursor = blocking_fetch_page(cursor)
        if not ads:
            print(f"[DEBUG] No ads found on listing page {i+1}")
            break
        all_ads.extend(ads)
        print(f"[DEBUG] Page {i+1}: {len(ads)} elan tapıldı")
        # small polite pause between pages
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    return all_ads


# ---------------- Telegram handlers & asyncio job ----------------
@dp.message()
async def on_message(message: types.Message):
    if message.text and message.text.strip().lower() == "/start":
        if message.chat.id not in subscribers:
            subscribers.add(message.chat.id)
            save_subscribers()
            print(f"[DEBUG] New subscriber: {message.chat.id}")
        await message.reply("Salam! Abunə oldunuz — yalnız bu andan sonra gələn elanları alacaqsınız.")


async def hourly_job():
    while True:
        print("[DEBUG] Yeni elanlar yoxlanılır...")
        # run blocking scraping in thread to avoid blocking event loop
        try:
            new_ads = await asyncio.to_thread(blocking_scrape_all, PAGES_TO_SCRAPE)
        except Exception as e:
            print(f"[ERROR] Scrape cycle failed: {e}")
            new_ads = []

        fresh = []
        for ad in new_ads:
            if ad["url"] not in seen_urls:
                seen_urls.add(ad["url"])
                fresh.append(ad)

        if fresh:
            for ad in fresh:
                text = f"🆕 Yeni elan:\n{ad['title']} | {ad['price']}\n{ad['url']}"
                for chat_id in list(subscribers):
                    try:
                        await bot.send_message(chat_id, text)
                        print(f"[DEBUG] Sent ad to {chat_id}: {ad['url']}")
                    except Exception as e:
                        print(f"[DEBUG] Error sending to {chat_id}: {e}")
        else:
            print("[DEBUG] No new ads this cycle.")

        print(f"[DEBUG] Növbəti yoxlama {CHECK_INTERVAL} saniyə sonra.")
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    load_subscribers()
    # start hourly_job + bot polling
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")

