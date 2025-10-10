import requests
import time
from bs4 import BeautifulSoup

BASE_URL = "https://tap.az/elanlar/elektronika/noutbuklar"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}



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


lst = scrape_all()

print(lst[0])
