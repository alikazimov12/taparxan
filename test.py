import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from aiogram.filters import Command

TOKEN = "8427693315:AAHrqQKu1ABD_dZcJA8PVF6_l66owypoW6c"
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

subscribers = set()  # Telegram chat_id-lərini burada saxlayacağıq

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
        # Mağaza elanlarını çıxarırıq
        paid_elem = card.select_one(".products-paid")
        if paid_elem and paid_elem.text.strip() != "":
            continue

        title = card.select_one(".products-i__name")
        price = card.select_one(".products-i__price")
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

async def scrape_all():
    all_ads = []
    cursor = None
    for _ in range(5):  # 5 səhifə çək
        ads, cursor = fetch_page(cursor)
        if not ads:
            break
        all_ads.extend(ads)
        await asyncio.sleep(1)
    return all_ads

async def send_ads(ads):
    for ad in ads:
        message = f"🆕 <b>{ad['title']}</b>\n💰 {ad['price']}\n🔗 {ad['url']}"
        for chat_id in subscribers:
            try:
                await bot.send_message(chat_id=chat_id, text=message)
            except Exception as e:
                print(f"Mesaj göndərilmədi {chat_id}: {e}")

async def hourly_job():
    seen = set()
    while True:
        print("Yeni elanlar yoxlanılır...")
        new_ads = await scrape_all()
        fresh_ads = [ad for ad in new_ads if ad["url"] not in seen]
        for ad in fresh_ads:
            seen.add(ad["url"])
        if fresh_ads:
            await send_ads(fresh_ads)
        await asyncio.sleep(3600)  # 1 saat gözləyir

@dp.message(Command("start"))
async def start(message: types.Message):
    subscribers.add(message.chat.id)
    await message.reply("Salam! Tap.az noutbuk elanları feed-ə qoşuldunuz. İndi bütün mövcud elanları göndərirəm...")
    ads = await scrape_all()
    await send_ads(ads)

async def main():
    # Hourly job-u background-da işə salırıq
    asyncio.create_task(hourly_job())
    # Bot-u polling ilə işə salırıq
    await dp.start_polling(bot)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

