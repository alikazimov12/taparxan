import asyncio
import json
import datetime
import time
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

# optional: use zoneinfo if available (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    HAVE_ZONEINFO = True
except Exception:
    HAVE_ZONEINFO = False

TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
bot = Bot(token=TOKEN)
dp = Dispatcher()

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

subscribers_file = "subscribers.json"
subscribers = set()
seen_ads = set()

# ----------- AZ time bootstrap ----------
def get_azerbaijan_now():
    """Return current Azerbaijan time as naive datetime (no tzinfo)"""
    if HAVE_ZONEINFO:
        try:
            az = datetime.datetime.now(ZoneInfo("Asia/Baku"))
            # return naive datetime for simpler arithmetic later
            return az.replace(tzinfo=None)
        except Exception as e:
            print(f"[DEBUG] zoneinfo failed: {e}")

    # fallback: use worldtime API
    try:
        r = requests.get("http://worldtimeapi.org/api/timezone/Asia/Baku", timeout=10)
        r.raise_for_status()
        data = r.json()
        # data['datetime'] e.g. "2025-10-11T19:25:36.123456+04:00"
        dt_str = data.get("datetime")
        if dt_str:
            # parse ignoring offset, then convert to naive local-datetime
            dt = datetime.datetime.fromisoformat(dt_str)
            return dt.replace(tzinfo=None)
    except Exception as e:
        print(f"[DEBUG] worldtimeapi fallback failed: {e}")

    # last resort: approximate by adding +4 hours to UTC (Azerbaijan UTC+4)
    now_utc = datetime.datetime.utcnow()
    return now_utc + datetime.timedelta(hours=4)


# Capture AZ time at start and local time at start; compute offset = AZ - local
LOCAL_START = datetime.datetime.now()
AZ_START = get_azerbaijan_now()
OFFSET_AZ_MINUS_LOCAL = AZ_START - LOCAL_START

print(f"[DEBUG] Local start: {LOCAL_START.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"[DEBUG] AZ start   : {AZ_START.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"[DEBUG] OFFSET (AZ - LOCAL): {OFFSET_AZ_MINUS_LOCAL}")

def current_az_now():
    """Compute current AZ time by applying persisted offset to current local time."""
    now_local = datetime.datetime.now()
    return now_local + OFFSET_AZ_MINUS_LOCAL

# START_TIME used for filtering (AZ time when script started)
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
        r = requests.get(ad_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        shop_link = soup.select_one('a[data-stat="shop-ad-go-shop-btn"]')
        if shop_link:
            print(f"[DEBUG] Mağaza elanı tapıldı, çıxarılır: {ad_url}")
            return True
    except Exception as e:
        print(f"[DEBUG] Xəta yoxlananda {ad_url}: {e}")
    return False

def fetch_page(cursor=None):
    params = {
        "keywords_source": "typewritten",
        "order": "newest",
    }
    if cursor:
        params["cursor"] = cursor

    r = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    ads = []

    for card in soup.select(".products-i"):
        title_elem = card.select_one(".products-name")
        price_elem = card.select_one(".products-price .price-val")
        link = card.select_one("a[href]")
        date_div = card.select_one(".products-created")

        if not link or not date_div:
            continue

        date_text = date_div.text.strip()  # məsələn "Bakı, bugün, 16:19"
        date_text_l = date_text.lower()

        # yalnız "bugün" elanlarını nəzərə al
        if "bugün" not in date_text_l:
            continue

        # parse the time part (after last comma)
        try:
            hour_min = date_text.split(",")[-1].strip()
            # build ad datetime in AZ timezone using current AZ date
            az_now = current_az_now()
            ad_time = datetime.datetime.combine(
                az_now.date(),
                datetime.datetime.strptime(hour_min, "%H:%M").time()
            )
        except Exception as e:
            # parse error -> skip
            print(f"[DEBUG] Time parse failed for '{date_text}': {e}")
            continue

        # compare with START_TIME_AZ (bot start AZ time)
        if ad_time < START_TIME_AZ:
            # posted before bot start -> skip
            continue

        ad_url = "https://tap.az" + link["href"]
        # optional: check shop ad (may be slow)
        try:
            if is_shop_ad(ad_url):
                # skip shop ads
                print(f"[DEBUG] Skipping shop ad (from ad page): {ad_url}")
                continue
        except Exception as e:
            print(f"[DEBUG] Error checking shop ad for {ad_url}: {e}")
            # if error when checking, we choose to skip checking and include the ad.
            # If you prefer to skip on error, uncomment next line:
            # continue

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
        time.sleep(1)
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
                    except Exception as e:
                        print(f"[DEBUG] Xəta {chat_id} göndərərkən: {e}")
        else:
            print("[DEBUG] No new ads this cycle.")
        print("[DEBUG] 1 saat gözlənilir...\n")
        await asyncio.sleep(60)  # realda 3600; test üçün dəyişə bilərsən

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )

if __name__ == "__main__":
    asyncio.run(main())

