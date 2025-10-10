import asyncio
import json
import datetime
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

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
start_time = datetime.datetime.now()

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
        r = requests.get(ad_url, headers=HEADERS)
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

    r = requests.get(BASE_URL, headers=HEADERS, params=params)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    ads = []

    for card in soup.select(".products-i"):
        title = card.select_one(".products-name")
        price = card.select_one(".products-price .price-val")
        link = card.select_one("a[href]")
        date_div = card.select_one(".products-created")

        if not link or not date_div:
            continue

        date_text = date_div.text.strip()  # məsələn "Bakı, bugün, 16:19"
        if "bugün" not in date_text.lower():
            continue

        try:
            hour_min = date_text.split(",")[-1].strip()
            ad_time = datetime.datetime.combine(
                start_time.date(),
                datetime.datetime.strptime(hour_min, "%H:%M").time()
            )
        except:
            continue

        if ad_time < start_time:
            continue

        ad_url = "https://tap.az" + link["href"]
        if is_shop_ad(ad_url):  # əgər mağaza linki varsa, keç
            continue

        ads.append({
            "title": title.text.strip() if title else "No title",
            "price": price.text.strip() if price else "No price",
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
        asyncio.sleep(1)
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
                    except Exception as e:
                        print(f"[DEBUG] Xəta {chat_id} göndərərkən: {e}")
        print("[DEBUG] 1 saat gözlənilir...\n")
        await asyncio.sleep(50)

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )

if __name__ == "__main__":
    asyncio.run(main())

