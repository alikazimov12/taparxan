import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
import json
import os
import time

TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
bot = Bot(token=TOKEN)
dp = Dispatcher()  # 3.x-də sadəcə boş Dispatcher

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

subscribers = set()
SEEN_FILE = "seen.json"

if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r") as f:
        seen = set(json.load(f))
else:
    seen = set()

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
        paid_div = card.select_one(".products-paid")
        # Mağaza yoxlaması: products-paid varsa və içində heç bir mətn yoxdursa → skip
        if paid_div:
            text_inside = paid_div.get_text(strip=True)
            if text_inside == "":
                continue

        title = card.select_one(".products-name")
        price = card.select_one(".products-price")
        link = card.select_one("a[href]")
        if not link:
            continue
        ads.append({
            "title": title.text.strip() if title else "No title",
            "price": price.text.strip() if price else "No price",
            "url": "https://tap.az" + link["href"]
        })

    new_cursor = None
    if "cursor=" in r.url:
        new_cursor = r.url.split("cursor=")[-1]
    return ads, new_cursor

def scrape_all():
    all_ads = []
    cursor = None
    for _ in range(5):
        ads, cursor = fetch_page(cursor)
        if not ads:
            break
        all_ads.extend(ads)
        time.sleep(1)
    return all_ads

async def send_ads(ads):
    for ad in ads:
        message = f"🆕 Yeni elan: {ad['title']} | {ad['price']} | {ad['url']}"
        for chat_id in subscribers:
            await bot.send_message(chat_id=chat_id, text=message)

async def hourly_job():
    global seen
    while True:
        print("Yeni elanlar yoxlanılır...")
        new_ads = scrape_all()
        fresh_ads = []
        for ad in new_ads:
            if ad["url"] not in seen:
                seen.add(ad["url"])
                fresh_ads.append(ad)
        if fresh_ads:
            await send_ads(fresh_ads)
            with open(SEEN_FILE, "w") as f:
                json.dump(list(seen), f)
        await asyncio.sleep(3600)

@dp.message(F.text == "/start")
async def start(message: types.Message):
    subscribers.add(message.chat.id)
    await message.reply(
        "Salam! Tap.az noutbuk elanları feed-ə qoşuldunuz.\n"
        "İndi yalnız yeni elanlar barədə bildiriş alacaqsınız."
    )
    # İlk dəfə qoşulanda mövcud elanları da göndər
    ads = scrape_all()
    fresh_ads = []
    for ad in ads:
        if ad["url"] not in seen:
            seen.add(ad["url"])
            fresh_ads.append(ad)
    if fresh_ads:
        await send_ads(fresh_ads)
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen), f)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(hourly_job())
    asyncio.run(dp.start_polling(bot))

