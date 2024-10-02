import os
import img2pdf
import toml
import sys
import time
import shutil
from loguru import logger
from natsort import natsorted
from playwright.sync_api import sync_playwright, Page

template = {"scraper": {"scale": 1, "cooldown_between_pages": 0.1}}

level = "DEBUG"

logger.remove()
logger.add(
    sys.stderr,
    format="[{time:HH:mm:ss}] <level>{message}</level>",
    level=level,
)
logger.add("logs/{time}.log", rotation="10 MB", level=level)

def screenshot_page(book_page: Page, page_number: int, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            book_page.locator(f'xpath=//*[@id="page_{page_number}"]').scroll_into_view_if_needed()
            time.sleep(0.1)
            book_page.locator(f'xpath=//*[@id="page_{page_number}"]').screenshot(
                path=f"temp/images/page_{page_number}.png"
            )
            logger.info(f"Страница {page_number} была снята")
            book_page.evaluate('''(xpath) => {
                const element = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (element) {
                    element.style.display = 'none';
                }
            }''', '//*[@id="viewer__wrapper__notifications-new-bottom"]')
            return True
        except Exception as e:
            logger.error(f"Попытка {attempt + 1} не удалась для страницы {page_number}: {str(e)}")
            if attempt == max_retries - 1:
                logger.error(f"Не удалось получить страницу {page_number} после {max_retries} попыток!")
                return False
            book_page.evaluate('window.scrollBy(4000, 0);')
            time.sleep(1) 
    return False


def main():
    settings: dict

    if not os.path.isfile("settings.toml"):
        logger.info("Файл настроек не найден, создаётся шаблон")

        login = input("Введите логин Юрайта: ")
        logger.info(f"Логин введён: {login}")

        password = input("Введите пароль: ")
        logger.info("Пароль введён.")

        user = {"user": {"login": login, "password": password}}

        settings = user | template

        with open("settings.toml", "w") as f:
            toml.dump(settings, f)

        logger.info(
            "Создался файл settings.toml. Все ваши данные были сохранены в этом файле."
        )

    else:

        with open("settings.toml", "r") as f:
            settings = toml.load(f)

    logger.debug(settings)

    book = "https://urait.ru/book/ekonomika-organizacii-545336"
    wrapper = '//*[@id="viewer__wrapper__elements"]'

    # Запуск браузера
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False,  # Set to True for headless mode
            slow_mo=50,  # Slows down Playwright operations by 50ms
            ignore_default_args=["--disable-application-cache"],
        )

        context = browser.new_context(
            viewport={"width": 2000 * settings["scraper"]["scale"], "height": 2000 * settings["scraper"]["scale"]},
            device_scale_factor=settings["scraper"]["scale"]
            # user_agent="MyCustomUser/Agent",
        )

        page = context.new_page()

        page.goto(book, wait_until="domcontentloaded")

        time.sleep(5)
        page.locator(
            'xpath=//*[@id="modal-popup"]/div/div[2]/a'
        ).click()  # Модальное уведомление
        page.locator(
            "xpath=/html/body/header/div/div/div[5]/div[3]/div[1]/a[1]"
        ).click()  # Кнопка входа
        page.locator('xpath=//*[@id="email"]').nth(1).fill(settings["user"]["login"])
        time.sleep(1)
        page.locator('xpath=//*[@id="password"]').nth(0).fill(
            settings["user"]["password"]
        )
        page.locator("button.button-orange:nth-child(1)").click()
        time.sleep(5)
        page.locator(".data > div:nth-child(1)").click()
        time.sleep(1)

        logger.info(
            f'Книга под названием: {page.locator('xpath=//*[@id="book"]/div[2]/div[1]/div[1]/h1').text_content()}'
        )
        with context.expect_page() as book_page:
            page.locator('xpath=//*[@id="book"]/div[2]/div[1]/div[3]/div[1]/a').click()

        book_page = book_page.value

        time.sleep(10)

        book_page.evaluate("window.scrollTo(0, 0);")

        page_count = book_page.locator(
            'xpath=//*[@id="viewer__bar__pages-scale"]/span[2]'
        ).text_content()

        if not page_count:
            sys.exit(1)

        page_count = int(page_count[2:].strip())

        logger.info(f"Обнаружено {page_count} листов в книге")

        for i in range(1, page_count + 1):
            if not screenshot_page(book_page, i):
                logger.error("Выход из программы из-за неудачной попытки получения страницы.")
                sys.exit(1)

        browser.close()

    folder_path = "temp/images"

    image_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path)]
    image_files.sort()

    image_files = natsorted(image_files)
    print(image_files)

    if not image_files:
        logger.error("Конвертация в PDF файл не успешна, изображений нет!")
        sys.exit(1)

    try:
        pdf_bytes = img2pdf.convert(image_files)

        if pdf_bytes is None:
            logger.error("Конвертация в PDF вернула None.")
            sys.exit(1)

        with open("output.pdf", "wb") as f:
            f.write(pdf_bytes)

    except Exception as e:
        logger.error(f"Исключение при конвертации в PDF: {e}")
        sys.exit(1)
    
    finally:
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path) 


if __name__ == "__main__":
    main()
