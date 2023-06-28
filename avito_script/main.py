import functools
import logging
from pathlib import Path
import re
import sys
from time import sleep
from typing import Iterable

from bs4 import BeautifulSoup
from fake_useragent import FakeUserAgent
import pandas as pd
import requests

# названия столбцов, допускается пополнение кортежа или удаление элементов
cols = (
    "Заголовок", "Марка", "Модель", "Дата", "Цена", "Локация", "Ссылка",
    "Год выпуска", "Поколение", "Состояние", "Модификация", "Объём двигателя",
    "Тип двигателя", "Коробка передач", "Привод", "Тип кузова", "Цвет", "Руль",
    "Ёмкость топливного бака", "Расход топлива смешанный", "Разгон до 100 км/ч",
    "Длина", "Высота", "Дорожный просвет", "Колея передняя", "Колея задняя",
    "VIN или номер кузова", "ПТС", "Описание",
)


class QueryError(Exception):
    """Исключение, возникающее при парсинге html и 403 ответе"""


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


def get_pagen_urls(pagens: int = 1,
                   radius: int = 200,
                   city: str = "perm") -> Iterable[str]:
    """
    Формирует ссылки страниц с пагинацией, где на каждой предствлены 50 авто
    Самое важное - указать число страниц пагинации
    Либо заменить текующую ссылку url_pagen на нужную и отформатировать p={page},
    где p={page} - число страниц пагинации
    """
    url_pagen = "https://www.avito.ru/{city}/avtomobili?cd=1&p={page}&radius={radius}&searchRadius={radius}"
    return (url_pagen.format(page=i, radius=radius, city=city) for i in range(1, pagens + 1))


def save_to_excel(data: dict[str, str | None]) -> None:
    """Сохраняет сформированный словарь в файл"""
    path = Path(__file__).parent.joinpath("avito_cars.xlsx")
    if not path.exists():
        new_data = {key: list() for key in cols}
        df = pd.DataFrame(new_data)
        with pd.ExcelWriter(path) as writer:  # pyright: ignore
            df.to_excel(writer, index=False)
        logging.info("Файл avito_cars.xlsx создан")
    new_data = {key: [value] for key, value in data.items()}
    df = pd.DataFrame(new_data)
    with pd.ExcelWriter(
            path, mode="a", if_sheet_exists="overlay"
    ) as writer:  # pyright: ignore
        start_row = writer.sheets["Sheet1"].max_row
        df.to_excel(writer, index=False, header=False, startrow=start_row)
    logging.info("Автомобиль успешно добавлен в avito_cars.xlsx")


def get_card_markup(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise QueryError("Ошибка запроса к карточке с автомобилем")
    return response.content.decode()


def get_details_markup(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise QueryError("Ошибка запроса к характеристикам автомобиля")
    return response.content.decode()


def parse_pagen(markup_pagen: str) -> list[str]:
    soup = BeautifulSoup(markup_pagen, "lxml")
    card_urls = [
    f'https://www.avito.ru{card.find("div", class_="iva-item-title-py3i_").find("a")["href"]}'
    for card in soup.find_all("div", class_="iva-item-body-KLUuy")
    ]
    return card_urls


@error_handler
def get_card_urls(session: requests.Session, pagen_url: str) -> list[str]:
    response = session.get(pagen_url, headers=headers, timeout=10)
    try:
        card_urls = parse_pagen(response.content.decode())
    except Exception:
        raise QueryError("Не удалось получить ссылки на автомобили")
    return card_urls


def parse_card_details(markup_card_data: str) -> dict[str, str]:
    """Извлекает дополнительную информацию о характеристиках автомобиля"""
    soup = BeautifulSoup(markup_card_data, "lxml")
    full_details = {k.text: v.text for i in  soup.find_all("div", class_="desktop-1jb7eb2")
            for k, v in [i.find_all("span")]}
    return dict(filter(lambda tpl: tpl[0] in cols, full_details.items()))


def parse_card(card_markup: str, card_url: str) -> tuple[str | None, dict]:
    """Извлекает нужную информацию с карточки с автомобилем"""
    soup = BeautifulSoup(card_markup, "lxml")
    main_data = {key: None for key in cols}
    try:
        details_url = "https://www.avito.ru" + soup.find("div",
        class_="params-specification-__5qD").find("a")["href"]  # pyright: ignore
    except (KeyError, TypeError):
        details_url = None
    title = soup.find("span", class_="title-info-title-text")
    if title:
        brand, model = title.text.split()[0], title.text.split()[1].strip(",")
    else:
        brand, model = None, None
    date = soup.find("span", {"data-marker": "item-view/item-date"})
    price = soup.find("span", {"class": "styles-module-size_m-Co_QG", "itemprop": "price"})
    loc = soup.find("span", class_="style-item-address__string-wt61A")
    desc = soup.find("div", class_="style-item-description-html-qCwUL")
    try:
        data = {i[0]: i[1] for i in map(lambda x: re.split(r": ", x),
                (i.text for i in soup.find("ul",  # pyright: ignore
                class_="params-paramsList-zLpAu")))}
    except Exception:
        data = {}
    data.update(dict(Заголовок=title.text if title else None, Марка=brand,
                     Модель=model, Дата=date.text.strip("· ") if date else None,
                     Цена=price.text if price else None, Локация=loc.text if loc else None,
                     Описание=desc.text if desc else None, Ссылка=card_url))
    main_data.update(data)  # pyright: ignore
    return details_url, main_data


@error_handler
def proceed_main_card_data(session: requests.Session,
                           card_url: str) -> tuple[str, dict] | None:
    """Первичный сбор данных для автомобиля"""
    card_markup = get_card_markup(session, card_url)
    details_url, data = parse_card(card_markup, card_url)
    if details_url is None:
        return save_to_excel(data)
    return details_url, data


@error_handler
def proceed_full_card_data(session: requests.Session,
                           details_url: str, data: dict) -> None:
    """Вторичный сбор данных для автомобиля"""
    details_markup = get_details_markup(session, details_url)
    details = parse_card_details(details_markup)
    data.update(details)
    save_to_excel(data)


if __name__ == "__main__":
    for pagen_url in get_pagen_urls():
        headers = {"user-agent": FakeUserAgent().random}
        session = requests.Session()
        for card_url in get_card_urls(session, pagen_url):
            result = proceed_main_card_data(session, card_url)
            sleep(2)
            if result: proceed_full_card_data(session, *result)
            sleep(3)
        session.close()
