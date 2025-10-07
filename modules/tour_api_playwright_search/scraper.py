import asyncio
import xml.etree.ElementTree as ET
import math
from playwright.async_api import Page

# --- Import modules for each search type and common utilities ---
from .common import (
    get_page_context, close_page_context, go_to_page, scrape_item_detail_xml,
    BASE_URL, LOCATION_BASE_URL, LANGUAGE_MAP
)
# Dropdown functions are now self-contained in area.search
from .area.search import (
    get_sigungu_options, get_large_category_options, 
    get_medium_category_options, get_small_category_options
)

# --- Re-export dropdown functions for app.py to use ---
__all__ = [
    'get_search_results', 'get_item_detail_xml', 'LANGUAGE_MAP',
    'get_sigungu_options', 'get_large_category_options', 
    'get_medium_category_options', 'get_small_category_options'
]

async def _navigate_to_results_page(page: Page, **kwargs):
    """Navigates to the base URL, sets language, and selects all dropdown options before search."""
    search_type = kwargs.get("search_type", "area")
    target_url = LOCATION_BASE_URL if search_type == "location" else BASE_URL
    await page.goto(target_url, timeout=90000)
    await page.wait_for_load_state('networkidle')

    # Language
    language = kwargs.get("language")
    if language and language != "한국어":
        await page.locator('button.btn-lang').click()
        await page.locator(f'ul.lang-list a[data-lang="{LANGUAGE_MAP[language]}"]').click()
        await page.wait_for_load_state('networkidle')

    # Area-based search dropdowns
    if search_type == "area":
        province = kwargs.get("province")
        sigungu = kwargs.get("sigungu")
        tourism_type = kwargs.get("tourism_type")
        cat1, cat2, cat3 = kwargs.get("cat1"), kwargs.get("cat2"), kwargs.get("cat3")

        if province and province != "전국":
            await page.locator('button:has-text("지역 선택")').click()
            await page.locator(f'div.modal.region-modal.on a[name="areaCd"]:has-text("{province}")').click()
            await page.wait_for_timeout(500)
            if sigungu and sigungu != "전체":
                await page.locator(f'div.modal.region-modal.on a[name="signguCd"]:has-text("{sigungu}")').click()
            await page.locator('div.modal.region-modal.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')
        
        if tourism_type and tourism_type != "선택 안함":
            await page.locator('button:has-text("관광타입 선택")').click()
            await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
            await page.locator('div.modal#popup4.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')

        if cat1 and cat1 != "선택 안함":
            await page.locator('button:has-text("서비스 분류 선택")').click()
            await page.wait_for_selector('div.modal#popup1.on')
            await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{cat1}")').click()
            await page.wait_for_timeout(500)
            if cat2 and cat2 != "선택 안함":
                await page.locator(f'div.modal#popup1.on a[name="cat2"]:has-text("{cat2}")').click()
                await page.wait_for_timeout(500)
            if cat3 and cat3 != "선택 안함":
                await page.locator(f'div.modal#popup1.on a[name="cat3"]:has-text("{cat3}")').click()
            await page.locator('div.modal#popup1.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')

    # Location-based search inputs
    elif search_type == "location":
        await page.locator('input#searchXCoord').fill(kwargs.get("map_x", ""))
        await page.locator('input#searchYCoord').fill(kwargs.get("map_y", ""))
        await page.locator('input#searchRadius').fill(kwargs.get("radius", "2000"))
        tourism_type = kwargs.get("tourism_type")
        if tourism_type and tourism_type != "선택 안함":
            await page.locator('button:has-text("관광타입 선택")').click()
            await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
            await page.locator('div.modal#popup4.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')

async def get_search_results(pageNo=1, temp_dir: str = "", totalPages: int = 0, **kwargs):
    """The main function to get search results. It orchestrates the process."""
    p, browser, page = await get_page_context()
    try:
        await _navigate_to_results_page(page, **kwargs)
        
        search_button_locator = page.get_by_role("button", name="검색", exact=True)
        await search_button_locator.wait_for(state='visible')

        api_url_pattern = "/KorService2/locationBasedList2" if kwargs.get("search_type") == "location" else "/KorService2/areaBasedList2"

        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=30000
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

async def get_item_detail_xml(params):
    """The main function to get detail XML. It orchestrates the process."""
    p, browser, page = await get_page_context()
    try:
        await _navigate_to_results_page(page, **params)
        
        search_button_locator = page.get_by_role("button", name="검색", exact=True)
        await search_button_locator.wait_for(state='visible')

        api_url_pattern = "/KorService2/locationBasedList2" if params.get("search_type") == "location" else "/KorService2/areaBasedList2"

        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=30000
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

