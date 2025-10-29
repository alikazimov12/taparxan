import asyncio
import json
import datetime
import time
import cloudscraper
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

# Telegram bot token
TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Base URL
BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0.6613.138 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "az,en-US;q=0.9,en;q=0.8",
    "Referer": "https://tap.az/",
    "Connection": "keep-alive",
}

# cloudscraper obyekti
scraper = cloudscraper.create_scraper()

subscribers_file = "subscribers.json"
subscribers = set()
seen_ads = set()

# ----------- AZ time bootstrap ----------
def get_azerbaijan_now():
    """Return current Azerbaijan time as naive datetime (no tzinfo)"""
    try:
        from zoneinfo import ZoneInfo
        az = datetime.datetime.now(ZoneInfo("Asia/Baku"))
        return az.replace(tzinfo=None)
    except Exception:
        now_utc = datetime.datetime.utcnow()
        return now_utc + datetime.timedelta(hours=4)

LOCAL_START = datetime.datetime.now()
AZ_START = get_azerbaijan_now()
OFFSET_AZ_MINUS_LOCAL = AZ_START - LOCAL_START

def current_az_now():
    now_local = datetime.datetime.now()
    return now_local + OFFSET_AZ_MINUS_LOCAL

START_TIME_AZ = AZ_START

# ----------------------------------------

def load_subscribers():
    global subscribers
    try:
        with open(subscribers_file, "r") as f:
            subscribers = set(json.load(f))
    except:
        subscribers = set()

def save_subscribers():
    with open(subscribers_file, "w") as f:
        json.dump(list(subscribers), f)

load_subscribers()

def is_shop_ad(ad_url):
    """Elanın səhifəsinə girib yoxlayır, mağaza linki varsa True qaytarır"""
    try:
        r = scraper.get(ad_url, headers=HEADERS, timeout=20)
        if r.status_code == 403:
            print(f"[DEBUG] 403 alındı: {ad_url}")
            return True
        soup = BeautifulSoup(r.text, "html.parser")
        shop_link = soup.select_one('a[data-stat="shop-ad-go-shop-btn"]')
        if shop_link:
            print(f"[DEBUG] Mağaza elanı tapıldı, çıxarılır: {ad_url}")
            return True
    except Exception as e:
        print(f"[DEBUG] Xəta yoxlananda {ad_url}: {e}")
    return False

def fetch_page(cursor=None):
    params = {"keywords_source": "typewritten", "order": "newest"}
    if cursor:
        params["cursor"] = cursor

    r = scraper.get(BASE_URL, headers=HEADERS, params=params, timeout=20)
    if r.status_code == 403:
        print("[ERROR] 403 Forbidden - Cloudflare səni bloklayıb.")
        return [], None

    soup = BeautifulSoup(r.text, "html.parser")
    ads = []

    for card in soup.select(".products-i"):
        title_elem = card.select_one(".products-name")
        price_elem = card.select_one(".products-price .price-val")
        link = card.select_one("a[href]")
        date_div = card.select_one(".products-created")

        if not link or not date_div:
            continue

        date_text = date_div.text.strip().lower()
        if "bugün" not in date_text:
            continue

        try:
            hour_min = date_text.split(",")[-1].strip()
            az_now = current_az_now()
            ad_time = datetime.datetime.combine(
                az_now.date(),
                datetime.datetime.strptime(hour_min, "%H:%M").time()
            )
        except Exception:
            continue

        if ad_time < START_TIME_AZ:
            continue

        ad_url = "https://tap.az" + link["href"]

        if is_shop_ad(ad_url):
            continue

        ads.append({
            "title": title_elem.text.strip() if title_elem else "No title",
            "price": price_elem.text.strip() if price_elem else "No price",
            "url": ad_url
        })

    new_cursor = None
    if "cursor=" in r.url:
        new_cursor = r.url.split("cursor=")[-1]
    print(f"[DEBUG] Fetched page, {len(ads)} elan tapıldı")
    return ads, new_cursor

def scrape_all(pages=2):
    all_ads = []
    cursor = None
    for i in range(pages):
        ads, cursor = fetch_page(cursor)
        if not ads:
            break
        all_ads.extend(ads)
        time.sleep(3)
    return all_ads

@dp.message()
async def cmd_start(message: types.Message):
    if message.chat.id not in subscribers:
        subscribers.add(message.chat.id)
        save_subscribers()
    await message.answer("Salam! Sən artıq yeni elanlara abunəsən.")

async def hourly_job():
    global seen_ads
    while True:
        print("[DEBUG] Yeni elanlar yoxlanılır...")
        try:
            new_ads = scrape_all()
        except Exception as e:
            print(f"[ERROR] scrape_all failed: {e}")
            new_ads = []

        fresh_ads = [ad for ad in new_ads if ad["url"] not in seen_ads]
        for ad in fresh_ads:
            seen_ads.add(ad["url"])
            text = f"🆕 Yeni elan:\n{ad['title']} | {ad['price']}\n{ad['url']}"
            for chat_id in subscribers:
                try:
                    await bot.send_message(chat_id, text)
                except Exception as e:
                    print(f"[DEBUG] Xəta {chat_id} göndərərkən: {e}")
        print("[DEBUG] 1 saat gözlənilir...\n")
        await asyncio.sleep(60)

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )

if __name__ == "__main__":
    asyncio.run(main())

