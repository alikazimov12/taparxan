import asyncio
import json
import datetime
import random
import time
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

# Optional cloudscraper fallback (install with `pip install cloudscraper`)
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False

# ---------------- CONFIG ----------------
TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
bot = Bot(token=TOKEN)
dp = Dispatcher()

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
subscribers_file = "subscribers.json"

# Put your proxies here as strings "http://ip:port" or "http://user:pass@ip:port".
# Leave empty list to try without proxies.
PROXIES = [
    # "http://167.86.74.155:21966",
    # "http://user:pass@1.2.3.4:8080",
]

# User-Agent rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
]

# Runtime / behavior parameters
MAX_PROXY_TRIES = 4
REQUEST_TIMEOUT = 15  # seconds
MIN_REQUEST_DELAY = 0.5
MAX_REQUEST_DELAY = 1.2

subscribers = set()
seen_ads = set()
start_time = datetime.datetime.now()

# ---------------- helper: subscribers persistence ----------------
def load_subscribers():
    global subscribers
    try:
        with open(subscribers_file, "r") as f:
            subscribers = set(json.load(f))
    except Exception:
        subscribers = set()

def save_subscribers():
    with open(subscribers_file, "w") as f:
        json.dump(list(subscribers), f)

load_subscribers()

# ---------------- session & proxy rotation ----------------
session = requests.Session()

# Shuffle proxies once
if PROXIES:
    random.shuffle(PROXIES)
proxy_index = 0

def next_proxy():
    global proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[proxy_index % len(PROXIES)]
    proxy_index += 1
    return proxy

def get_headers():
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "az,en-US;q=0.9,en;q=0.8",
        "Referer": "https://tap.az/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "DNT": "1",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }
    return headers

def detect_cloudflare_body(text: str) -> bool:
    t = (text or "").lower()
    return ("cf-browser-verification" in t) or ("attention required!" in t) or ("cloudflare" in t and "check" in t)

def perform_request(url, method="GET", params=None, data=None, max_tries=MAX_PROXY_TRIES):
    """
    Try requests with rotating proxies and UA rotation.
    If Cloudflare JS challenge detected and cloudscraper available, try cloudscraper once.
    Returns response.text on success, raises last exception on failure.
    """
    last_exc = None
    tries = 0

    # first try: try different proxies (or no proxy if PROXIES empty)
    while tries < max_tries:
        proxy = next_proxy() if PROXIES else None
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        headers = get_headers()

        try:
            # polite random small delay
            time.sleep(random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY))
            print(f"[DEBUG] Requesting {url} (try {tries+1}/{max_tries}) proxy={proxy} UA={headers['User-Agent']}")
            resp = session.request(method, url, headers=headers, params=params, data=data, timeout=REQUEST_TIMEOUT, proxies=proxies)
            # If status code 403 or 429, treat as fail and try next proxy
            if resp.status_code == 403 or resp.status_code == 429:
                print(f"[DEBUG] Received status {resp.status_code} for {url} with proxy={proxy}")
                last_exc = requests.HTTPError(f"Status {resp.status_code}")
                tries += 1
                time.sleep(0.5 + tries * 0.3)
                continue

            # detect Cloudflare or challenge page inside body
            if detect_cloudflare_body(resp.text):
                print("[DEBUG] Cloudflare-like page detected in body.")
                last_exc = requests.HTTPError("Cloudflare challenge detected")
                tries += 1
                time.sleep(0.5 + tries * 0.3)
                continue

            resp.raise_for_status()
            return resp

        except Exception as e:
            print(f"[DEBUG] Request attempt failed (proxy={proxy}): {e}")
            last_exc = e
            tries += 1
            time.sleep(0.5 + tries * 0.3)

    # If all proxy tries exhausted, try cloudscraper fallback once (if available)
    if HAS_CLOUDSCRAPER:
        try:
            print("[DEBUG] Trying cloudscraper fallback...")
            scraper = cloudscraper.create_scraper(browser={'custom': get_headers()['User-Agent']})
            # cloudscraper accepts proxies param similar to requests
            proxy_for_cs = None if not PROXIES else {"http": PROXIES[0], "https": PROXIES[0]}
            resp = scraper.request(method, url, params=params, data=data, timeout=REQUEST_TIMEOUT, proxies=proxy_for_cs)
            if detect_cloudflare_body(resp.text):
                raise RuntimeError("Cloudscraper could not bypass Cloudflare")
            return resp
        except Exception as e:
            print(f"[DEBUG] cloudscraper fallback failed: {e}")
            last_exc = e

    # final fallback: try without proxy once
    try:
        print("[DEBUG] Final fallback: try without proxy and default headers")
        headers = get_headers()
        resp = session.request(method, url, headers=headers, params=params, data=data, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        if detect_cloudflare_body(resp.text):
            raise RuntimeError("Cloudflare detected in final fallback")
        return resp
    except Exception as e:
        print(f"[DEBUG] Final fallback failed: {e}")
        last_exc = e

    # if everything failed, raise last exception
    raise last_exc

# ---------------- check ad page for shop button ----------------
def is_shop_ad(ad_url):
    """Elanın səhifəsinə girib yoxlayır, mağaza linki varsa True qaytarır"""
    try:
        r = perform_request(ad_url)
        soup = BeautifulSoup(r.text, "html.parser")
        shop_link = soup.select_one('a[data-stat="shop-ad-go-shop-btn"]')
        if shop_link:
            print(f"[DEBUG] Mağaza elanı tapıldı, çıxarılır: {ad_url}")
            return True
    except Exception as e:
        print(f"[DEBUG] Xəta yoxlananda {ad_url}: {e}")
    return False

# ---------------- fetch listing page, filter by "bugün" and start_time ----------------
def fetch_page(cursor=None):
    params = {
        "keywords_source": "typewritten",
        "order": "newest",
    }
    if cursor:
        params["cursor"] = cursor

    # build URL with params for debug printing
    url = BASE_URL
    if cursor:
        url = BASE_URL + "?cursor=" + cursor

    try:
        r = perform_request(url, params=params)
    except Exception as e:
        print(f"[ERROR] Failed to fetch listing page: {e}")
        return [], None

    soup = BeautifulSoup(r.text, "html.parser")
    ads = []

    for card in soup.select(".products-i"):
        # quick filter: skip if listing-level indicates store (optional)
        if "products-shop" in (card.get("class") or []):
            print("[DEBUG] Skipping card due to products-shop class (listing-level)")
            continue

        title = card.select_one(".products-name")
        price = card.select_one(".products-price .price-val")
        link = card.select_one("a[href]")
        date_div = card.select_one(".products-created")

        if not link or not date_div:
            continue

        date_text = date_div.text.strip()  # e.g. "Bakı, bugün, 16:19"
        if "bugün" not in date_text.lower():
            # not today's ad — skip
            continue

        try:
            hour_min = date_text.split(",")[-1].strip()
            ad_time = datetime.datetime.combine(
                start_time.date(),
                datetime.datetime.strptime(hour_min, "%H:%M").time()
            )
        except Exception:
            # parse error — skip
            continue

        if ad_time < start_time:
            # placed before bot start — skip
            continue

        ad_url = "https://tap.az" + link["href"]

        # check if it's a shop ad by visiting ad page (this uses rotating proxies)
        try:
            if is_shop_ad(ad_url):
                # skip store ads
                continue
        except Exception as e:
            print(f"[DEBUG] Error while checking shop status for {ad_url}: {e}")
            # conservative choice: if check fails, skip including to avoid false positives OR include — choose include here:
            # continue  # <-- if you prefer to skip on error uncomment this
            pass

        ads.append({
            "title": title.text.strip() if title else "No title",
            "price": price.text.strip() if price else "No price",
            "url": ad_url
        })

    # extract cursor from response URL if present
    new_cursor = None
    try:
        final_url = r.url if r is not None else url
        if "cursor=" in final_url:
            new_cursor = final_url.split("cursor=")[-1]
    except:
        new_cursor = None

    print(f"[DEBUG] Fetched page, {len(ads)} elan tapıldı")
    return ads, new_cursor

# ---------------- scrape multiple pages ----------------
def scrape_all(pages=3):
    all_ads = []
    cursor = None
    for i in range(pages):
        ads, cursor = fetch_page(cursor)
        if not ads:
            print(f"[DEBUG] No ads found on page {i+1}")
            break
        all_ads.extend(ads)
        print(f"[DEBUG] Page {i+1}: {len(ads)} elan tapıldı")
        # polite pause between pages
        time.sleep(random.uniform(1.0, 2.0))
    return all_ads

# ---------------- telegram handlers & loop ----------------
@dp.message()
async def cmd_start(message: types.Message):
    if message.chat.id not in subscribers:
        subscribers.add(message.chat.id)
        save_subscribers()
        print(f"[DEBUG] New subscriber: {message.chat.id}")
    await message.answer("Salam! Sən artıq yeni elanlara abunəsən.")

async def hourly_job():
    global seen_ads
    while True:
        print("[DEBUG] Yeni elanlar yoxlanılır...")
        new_ads = scrape_all()
        fresh_ads = []
        for ad in new_ads:
            if ad["url"] not in seen_ads:
                seen_ads.add(ad["url"])
                fresh_ads.append(ad)
        if fresh_ads:
            for ad in fresh_ads:
                text = f"🆕 Yeni elan:\n{ad['title']} | {ad['price']}\n{ad['url']}"
                for chat_id in subscribers:
                    try:
                        await bot.send_message(chat_id, text)
                        print(f"[DEBUG] Sent to {chat_id}: {ad['url']}")
                    except Exception as e:
                        print(f"[DEBUG] Xəta {chat_id} göndərərkən: {e}")
        print("[DEBUG] Sleeping 1 hour...\n")
        await asyncio.sleep(60)

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )

if __name__ == "__main__":
    asyncio.run(main())

