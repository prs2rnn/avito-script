import functools
import json
import logging
from pathlib import Path
import re
import sys
from time import monotonic, sleep
from typing import Iterable

from bs4 import BeautifulSoup
from fake_useragent import FakeUserAgent
import requests

pagens = 1
domain = "https://www.avito.ru"


class QueryError(Exception):
    """base exception when query or parse page"""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
    datefmt="%d.%m.%Y, %H:%M:%S",
)


def error_handler(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except QueryError as err:
            logging.error(err)
    return wrapper


def get_pagen_urls(n: int) -> Iterable[str]:
    """returns all pagen links with each session"""
    url_pagen = "https://www.avito.ru/perm/avtomobili?cd=1&p={page}&radius=200&searchRadius=200"
    return (url_pagen.format(page=i) for i in range(1, n + 1))


def save_json(card_data: dict[str, str]) -> None:
    with open(Path(__file__).parent.joinpath("avito_cars.json"), "a",
              encoding="utf-8") as file:
        json.dump(card_data, file, ensure_ascii=False, indent=3)
        logging.info("saved car data in file successfully")


def get_card_markup(session: requests.Session, url: str) -> str:
    markup = session.get(url, headers=headers, timeout=10).content.decode()
    return markup


def get_details_markup(session: requests.Session, url: str) -> str:
    markup = session.get(url, headers=headers, timeout=10).content.decode()
    return markup


def parse_pagen(markup_pagen: str) -> list[str]:
    soup = BeautifulSoup(markup_pagen, "lxml")
    card_urls = [
    f'{domain}{card.find("div", class_="iva-item-title-py3i_").find("a")["href"]}'
    for card in soup.find_all("div", class_="iva-item-body-KLUuy")
    ]
    return card_urls


def get_card_urls(session: requests.Session, pagen_url: str) -> list[str]:
    markup_pagen = session.get(pagen_url, headers=headers, timeout=10).content.decode()
    card_urls = parse_pagen(markup_pagen)
    if not card_urls: raise QueryError("can't parse card urls. 403 response.")
    return card_urls


def parse_card_details(markup_card_data: str) -> dict[str, str]:
    """parse additional data from characteritics url page"""
    soup = BeautifulSoup(markup_card_data, "lxml")
    cols = ("Расход топлива смешанный", "Разгон до 100 км/ч",
            "Колея передняя", "Колея задняя", "Длина", "Высота",
            "Дорожный просвет", "Ёмкость топливного бака")
    full = {k.text: v.text for i in soup.find_all("div", class_="desktop-1jb7eb2")
            for k, v in [i.find_all("span")]}
    return dict(filter(lambda tpl: tpl[0] in cols, full.items()))


def parse_card(card_markup: str) -> tuple[str | None, dict]:
    soup = BeautifulSoup(card_markup, "lxml")
    try:
        card_data_url = domain + \
            soup.find("div", class_="params-specification-__5qD").find("a")["href"]  # pyright: ignore
    except Exception:
        card_data_url = None
    title = soup.find("span", class_="title-info-title-text")
    try:
        brand, model = title.text.split()[0], title.text.split()[1].strip(",")  # pyright: ignore
    except Exception:
        brand, model = None, None
    date = soup.find("span", {"data-marker": "item-view/item-date"})
    price = soup.find("span", {"class": "styles-module-size_m-Co_QG", "itemprop": "price"})
    loc = soup.find("span", class_="style-item-address__string-wt61A")
    desc = soup.find("div", class_="style-item-description-html-qCwUL")
    data = {i[0]: i[1] for i in map(lambda x: re.split(r": ", x),
            (i.text for i in soup.find("ul", class_="params-paramsList-zLpAu")))}  # pyright: ignore
    data.update(dict(Заголовок=title.text if title else None, Марка=brand,
                     Модель=model, Дата=date.text.strip("· ") if date else None,
                     Цена=price.text if price else None, Локация=loc.text if loc else None,
                     Описание=desc.text if desc else None))
    return card_data_url, data


def fill_details() -> dict[str, None]:
    cols = ("Расход топлива смешанный", "Разгон до 100 км/ч",
            "Колея передняя", "Колея задняя", "Длина", "Высота",
            "Дорожный просвет", "Ёмкость топливного бака")
    return {k: None for k in cols}


@error_handler
def proceed_full_card_data(session: requests.Session, card_url: str) -> None:
    card_markup = get_card_markup(session, card_url)
    details_url, data = parse_card(card_markup)
    if not data: raise QueryError("can't parse card. 403 response")
    if details_url is None:
        details = fill_details()
        data.update(details)
        return save_json(data)
    sleep(2)
    details_markup = get_details_markup(session, details_url)
    details = parse_card_details(details_markup)
    data.update(details)
    save_json(data)


if __name__ == "__main__":
    start = monotonic()
    for pagen_url in get_pagen_urls(pagens):
        headers = {"user-agent": FakeUserAgent().random}
        session = requests.Session()
        for card_url in get_card_urls(session, pagen_url):
            proceed_full_card_data(session, card_url)
            sleep(4)
    print(monotonic() - start)
