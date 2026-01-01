import asyncio
import json
import datetime
import random
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from faker import Faker
from datetime import datetime as dt, timezone, timedelta

# ================= CONFIG =================

TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"

SUBSCRIBERS_FILE = "subscribers.json"
SEEN_FILE = "seen_ads.json"

CHECK_INTERVAL_MIN = 50
CHECK_INTERVAL_MAX = 70

fake = Faker()
session = requests.Session()

HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "az,en;q=0.9"
}

bot = Bot(token=TOKEN)
dp = Dispatcher()

subscribers = set()
seen_ads = set()

# ================= LOG =================

def log(msg, level="INFO"):
    now = dt.now().strftime("%H:%M:%S")
    print(f"[{now}] [{level}] {msg}")

# ================= TIME =================

def az_now():
    return dt.now(timezone.utc).astimezone(
        timezone(timedelta(hours=4))
    ).replace(tzinfo=None)

# ================= HELPERS =================

def random_headers():
    h = HEADERS_BASE.copy()
    h["User-Agent"] = fake.user_agent()
    return h

def load_json(path):
    try:
        with open(path, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(list(data), f)

subscribers = load_json(SUBSCRIBERS_FILE)
seen_ads = load_json(SEEN_FILE)

# ================= SCRAPER =================

def is_shop_ad_sync(url):
    try:
        r = session.get(url, headers=random_headers(), timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        if soup.select_one('a[data-stat="shop-ad-go-shop-btn"]'):
            log(f"Mağaza elanı çıxarıldı → {url}", "SHOP")
            return True
        return False
    except Exception as e:
        log(f"Shop yoxlama xətası → {e}", "ERROR")
        return False

def fetch_page_sync():
    log("Tap.az səhifəsi çəkilir...")

    r = session.get(
        BASE_URL,
        headers=random_headers(),
        params={"order": "newest"},
        timeout=15
    )

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select(".products-i")

    log(f"Səhifədə {len(cards)} kart tapıldı")

    ads = []

    for card in cards:
        link = card.select_one("a[href]")
        date_div = card.select_one(".products-created")

        if not link or not date_div:
            continue

        if "bugün" not in date_div.text.lower():
            log("Köhnə elan skip edildi", "SKIP")
            continue

        try:
            hour_min = date_div.text.split(",")[-1].strip()
            ad_time = datetime.datetime.combine(
                az_now().date(),
                datetime.datetime.strptime(hour_min, "%H:%M").time()
            )
        except Exception as e:
            log(f"Vaxt parse xətası → {e}", "ERROR")
            continue

        title = card.select_one(".products-name")
        price = card.select_one(".products-price .price-val")

        ad = {
            "url": "https://tap.az" + link["href"],
            "title": title.text.strip() if title else "No title",
            "price": price.text.strip() if price else "No price",
            "time": ad_time
        }

        log(f"TAPILDI → {ad['title']} | {ad['price']}")
        ads.append(ad)

    log(f"Uyğun elan sayı: {len(ads)}")
    return ads

async def fetch_page():
    return await asyncio.to_thread(fetch_page_sync)

async def is_shop_ad(url):
    return await asyncio.to_thread(is_shop_ad_sync, url)

# ================= BOT =================

@dp.message()
async def start_cmd(message: types.Message):
    subscribers.add(message.chat.id)
    save_json(SUBSCRIBERS_FILE, subscribers)
    await message.answer("✅ Yeni elanlara abunə oldun.")

async def monitor_loop():
    global seen_ads

    while True:
        log("Yeni elanlar yoxlanılır...")

        try:
            ads = await fetch_page()
        except Exception as e:
            log(f"Scrape xətası → {e}", "ERROR")
            ads = []

        new_count = 0

        for ad in ads:
            if ad["url"] in seen_ads:
                log(f"Artıq görülüb → {ad['url']}", "SEEN")
                continue

            if await is_shop_ad(ad["url"]):
                continue

            seen_ads.add(ad["url"])
            save_json(SEEN_FILE, seen_ads)

            log(f"YENİ ELAN → {ad['title']} | {ad['price']}", "NEW")

            text = f"🆕 Yeni elan:\n{ad['title']} | {ad['price']}\n{ad['url']}"

            for chat_id in subscribers:
                try:
                    await bot.send_message(chat_id, text)
                except Exception as e:
                    log(f"Telegram error → {e}", "ERROR")

            new_count += 1

        log(f"Dövr bitdi | Yeni elan: {new_count}")
        log("Növbəti yoxlama gözlənilir...\n")

        await asyncio.sleep(random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        monitor_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())

