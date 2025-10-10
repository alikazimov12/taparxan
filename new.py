import asyncio
import json
import time
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types

TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"  # buraya bot tokenini yaz
CHAT_FILE = "subscribers.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

# subscribers.json faylından istifadəçiləri yüklə
def load_subscribers():
    try:
        with open(CHAT_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

# subscribers.json faylına istifadəçiləri yaz
def save_subscribers(subscribers):
    with open(CHAT_FILE, "w") as f:
        json.dump(list(subscribers), f)

subscribers = load_subscribers()
seen_ads = set()

def fetch_page(cursor=None):
    params = {
        "keywords_source": "typewritten",
        "order": "newest",
        "q[user_id]": "",
        "q[contact_id]": "",
        "q[price][]": "",
        "q[region_id]": "",
        "q[keywords]": "",
        "p[822]": "",
        "p[769]": "",
        "p[858]": ""
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

def scrape_all(pages=3):
    all_ads = []
    cursor = None
    for _ in range(pages):
        ads, cursor = fetch_page(cursor)
        if not ads:
            break
        all_ads.extend(ads)
        time.sleep(1)
    return all_ads

# Telegram /start komandası
@dp.message()
async def cmd_start(message: types.Message):
    if message.chat.id not in subscribers:
        subscribers.add(message.chat.id)
        save_subscribers(subscribers)
    await message.answer("Salam! Sən artıq yeni elanlara abunəsən.")

# Bot loopu: yeni elanları yoxlayır və istifadəçilərə göndərir
async def hourly_job():
    global seen_ads
    while True:
        print("Yeni elanlar yoxlanılır...")
        new_ads = scrape_all()
        for ad in new_ads:
            if ad["url"] not in seen_ads:
                seen_ads.add(ad["url"])
                text = f"🆕 Yeni elan:\n{ad['title']} | {ad['price']}\n{ad['url']}"
                for chat_id in subscribers:
                    try:
                        await bot.send_message(chat_id, text)
                    except Exception as e:
                        print(f"Xəta {chat_id} göndərərkən: {e}")
        print("1 saat gözlənilir...\n")
        await asyncio.sleep(60)  # hər 1 saat

async def main():
    # hourly_job və bot polling eyni zamanda
    await asyncio.gather(
        dp.start_polling(bot),
        hourly_job()
    )

if __name__ == "__main__":
    asyncio.run(main())

