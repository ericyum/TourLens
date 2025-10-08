import asyncio
import xml.etree.ElementTree as ET
import math
from playwright.async_api import Page

from ..common import (
    get_page_context, close_page_context, go_to_page, scrape_item_detail_xml,
    DATE_SEARCH_BASE_URL, LANGUAGE_MAP
)

async def _navigate_to_date_search_page(page: Page, **kwargs):
    """Navigates to the date search URL, sets all filters."""
    await page.goto(DATE_SEARCH_BASE_URL, timeout=0)
    await page.wait_for_load_state('networkidle')

    # Language
    language = kwargs.get("language")
    if language and language != "한국어":
        await page.locator('button.btn-lang').click()
        await page.locator(f'ul.lang-list a[data-lang="{LANGUAGE_MAP[language]}"]').click()
        await page.wait_for_load_state('networkidle')

    # Area
    province = kwargs.get("province")
    sigungu = kwargs.get("sigungu")
    if province and province != "전국":
        await page.locator('button:has-text("지역 선택")').click()
        await page.locator(f'div.modal.region-modal.on a[name="areaCd"]:has-text("{province}")').click()
        await page.wait_for_timeout(500)
        if sigungu and sigungu != "전체":
            await page.locator(f'div.modal.region-modal.on a[name="signguCd"]:has-text("{sigungu}")').click()
        await page.locator('div.modal.region-modal.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')

    # Dates
    start_date = kwargs.get("start_date", "")
    end_date = kwargs.get("end_date", "")
    if start_date:
        await page.locator('div.search-filter input[title="시작날짜(날짜형식:YYYY-MM-DD)"]').fill(start_date)
    if end_date:
        await page.locator('div.search-filter input[title="종료날짜(날짜형식:YYYY-MM-DD)"]').fill(end_date)

async def get_date_search_results(pageNo=1, temp_dir: str = "", totalPages: int = 0, **kwargs):
    """The main function to get date search results for a single page."""
    p, browser, page = await get_page_context()
    try:
        await _navigate_to_date_search_page(page, **kwargs)

        search_button_locator = page.get_by_role('button', name='검색', exact=True)
        api_url_pattern = "/KorService2/searchFestival2"

        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=0
        ) as response_info:
            await search_button_locator.click()

        response = await response_info.value
        xml_content = await response.text()

        if pageNo > 1:
            await go_to_page(page, pageNo, totalPages)
            xml_content = await page.locator("textarea#ResponseXML").input_value()

        root = ET.fromstring(xml_content)
        items = root.findall('.//body/items/item')

        total_count_element = root.find('.//body/totalCount')
        total_count = int(total_count_element.text) if total_count_element is not None and total_count_element.text else len(items)

        results = []
        for item in items:
            item_xml_string = ET.tostring(item, encoding='unicode')
            results.append({
                "title": item.findtext('title'), "image": item.findtext('firstimage'),
                "mapx": item.findtext('mapx'), "mapy": item.findtext('mapy'),
                "contentid": item.findtext('contentid'), "contenttypeid": item.findtext('contenttypeid'),
                "initial_item_xml": item_xml_string
            })

        req_url = await page.locator("p#RequestURL").text_content()
        return results, req_url, xml_content, total_count
    finally:
        await close_page_context(p, browser)

async def get_date_search_item_detail_xml(params):
    """The main function to get detail XML for a single item from a date search."""
    p, browser, page = await get_page_context()
    try:
        await _navigate_to_date_search_page(page, **params)

        search_button_locator = page.get_by_role('button', name='검색', exact=True)
        api_url_pattern = "/KorService2/searchFestival2"

        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=0
        ) as response_info:
            await search_button_locator.click()

        response = await response_info.value
        xml_content = await response.text()

        root = ET.fromstring(xml_content)
        total_count_element = root.find('.//body/totalCount')
        total_count = 0
        if total_count_element is not None and total_count_element.text:
            total_count = int(total_count_element.text)

        ITEMS_PER_PAGE = 12
        total_pages = math.ceil(total_count / ITEMS_PER_PAGE) if total_count > 0 else 1

        page_no = params.get("pageNo", 1)
        if page_no > 1:
            await go_to_page(page, page_no, total_pages)

        return await scrape_item_detail_xml(page, params)
    except Exception as e:
        raise e
    finally:
        await close_page_context(p, browser)
