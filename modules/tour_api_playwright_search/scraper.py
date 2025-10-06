import asyncio
import xml.dom.minidom
import re
import os
import requests
import html
from playwright.async_api import async_playwright, Page, expect
import xml.etree.ElementTree as ET

# --- Constants ---
BASE_URL = "https://api.visitkorea.or.kr/#/useInforArea"
LANGUAGE_MAP = {
    "한국어": "Kor", "영어": "Eng", "일어": "Jpn", "중국어(간체)": "Chs",
    "중국어(번체)": "Cht", "독일어": "Ger", "프랑스어": "Fre", "스페인어": "Spa", "러시아어": "Rus",
}

# --- Playwright Context Management ---
async def _get_page_context():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    page.set_default_timeout(60000)
    return p, browser, page

async def _close_page_context(p, browser):
    if browser and browser.is_connected():
        await browser.close()

# --- Scraper Core Logic ---

async def _navigate_to_results_page(page: Page, language, province, sigungu, tourism_type, cat1, cat2, cat3):
    await page.goto(BASE_URL, timeout=90000)
    await page.wait_for_timeout(2000)
    if language and language != "한국어":
        await page.locator('button.btn-lang').click()
        await page.locator(f'ul.lang-list a[data-lang="{LANGUAGE_MAP[language]}"]').click()
        await page.wait_for_load_state('networkidle')
    if province and province != "전국":
        await page.locator('button:has-text("지역 선택")').click()
        await page.locator(f'div.modal.region-modal.on a[name="areaCd"]:has-text("{province}")').click()
        await page.wait_for_timeout(500)
        if sigungu and sigungu != "전체":
            await page.locator(f'div.modal.region-modal.on a[name="signguCd"]:has-text("{sigungu}")').click()
        await page.locator('div.modal.region-modal.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
    if tourism_type:
        await page.locator('button:has-text("관광타입 선택")').click()
        await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
    if cat1 or cat2 or cat3:
        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        if cat1: await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{cat1}")').click(); await page.wait_for_timeout(500)
        if cat2: await page.locator(f'div.modal#popup1.on a[name="cat2"]:has-text("{cat2}")').click(); await page.wait_for_timeout(500)
        if cat3: await page.locator(f'div.modal#popup1.on a[name="cat3"]:has-text("{cat3}")').click()
        await page.locator('div.modal#popup1.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
    await page.locator('div.search-filter button:has-text("검색")').click()
    await page.wait_for_selector('textarea#ResponseXML', timeout=30000)

async def _go_to_page(page: Page, target_page: int):
    if target_page <= 1: return
    for _ in range(30):
        current_page_text = await page.locator("div.paging button.on").text_content(timeout=5000)
        if int(current_page_text) == target_page: return
        if await page.locator(f"div.paging button[value='{target_page}']").is_visible():
            await page.locator(f"div.paging button[value='{target_page}']").click()
        elif target_page > int(current_page_text):
            await page.locator('div.paging button[name="next"]').click()
        else:
            await page.locator('div.paging button[name="prev"]').click()
        await page.wait_for_load_state('networkidle')

async def get_search_results(language, province, sigungu, tourism_type, cat1, cat2, cat3, pageNo=1, temp_dir: str = ""):
    p, browser, page = await _get_page_context()
    try:
        await _navigate_to_results_page(page, language, province, sigungu, tourism_type, cat1, cat2, cat3)
        if pageNo > 1: await _go_to_page(page, pageNo)
        await page.wait_for_function("document.querySelector('textarea#ResponseXML').value.length > 10", timeout=15000)
        xml_content = await page.locator("textarea#ResponseXML").input_value()
        root = ET.fromstring(xml_content)
        total_count = int(root.find('.//body/totalCount').text)
        items = root.findall('.//body/items/item')
        results = []
        for item in items:
            results.append({
                "title": item.findtext('title'), "image": item.findtext('firstimage'),
                "mapx": item.findtext('mapx'), "mapy": item.findtext('mapy'),
                "contentid": item.findtext('contentid'), "contenttypeid": item.findtext('contenttypeid')
            })
        req_url = await page.locator("p#RequestURL").text_content()
        return results, req_url, xml_content, total_count
    finally:
        await _close_page_context(p, browser)

async def get_item_detail_xml(params):
    p, browser, page = await _get_page_context()
    try:
        await _navigate_to_results_page(page, **{k: v for k, v in params.items() if k in ['language', 'province', 'sigungu', 'tourism_type', 'cat1', 'cat2', 'cat3']})
        if params.get("pageNo", 1) > 1:
            await _go_to_page(page, params["pageNo"])

        await page.wait_for_function("document.querySelector('textarea#ResponseXML').value.length > 10", timeout=15000)
        xml_content = await page.locator("textarea#ResponseXML").input_value()
        root = ET.fromstring(xml_content)
        items = root.findall('.//body/items/item')

        title_to_click = None
        for item in items:
            if item.findtext('contentid') == params.get('contentid'):
                title_to_click = item.findtext('title')
                break

        if title_to_click is None: raise Exception(f"Could not find item with contentid '{params.get('contentid')}' on page {params.get('pageNo', 1)}.")

        await page.locator(f'ul.gallery-list li:has-text("{title_to_click}")').click()
        
        await page.wait_for_function("document.querySelector('textarea#ResponseXML').value.includes('<overview>')", timeout=15000)

        xml_textarea_locator = page.locator("textarea#ResponseXML")

        if params.get("tab_name") == "공통정보":
            return await xml_textarea_locator.input_value()

        tab_button_locator = page.locator(f'button:has-text("{params.get("tab_name")}")')
        
        if not await tab_button_locator.is_visible():
            return "<response><body><items></items></body></response>"

        initial_xml = await xml_textarea_locator.input_value()
        await tab_button_locator.click()

        try:
            js_function = "(initialXml) => document.querySelector('textarea#ResponseXML').value !== initialXml"
            await page.wait_for_function(js_function, arg=initial_xml, timeout=10000)
            new_xml = await xml_textarea_locator.input_value()
            if not new_xml.strip():
                 raise Exception("XML is empty, proceeding to HTML scrape.")
            return new_xml
        except Exception:
            try:
                tab_name = params.get("tab_name")
                await page.locator('div.tab-content.on h4').wait_for(state='attached', timeout=10000)
                tab_content_locator = page.locator("div.tab-content.on")

                await page.screenshot(path=f"debug_{tab_name}_fallback_entry.png")

                if (tab_name == "소개정보" or tab_name == "반복정보") and await tab_content_locator.locator("table").is_visible():
                    xml_item_content = ""
                    rows = await tab_content_locator.locator("tbody > tr").all()
                    for row in rows:
                        th_locator = row.locator("td.th")
                        td_locator = row.locator("td:not(.th)")
                        if await th_locator.count() > 0 and await td_locator.count() > 0:
                            th_text = await th_locator.first.text_content()
                            td_text = await td_locator.first.text_content()
                            tag_name = re.sub(r'[^A-Za-z0-9_가-힣]', '', th_text.strip())
                            if tag_name:
                                escaped_td_text = html.escape(td_text.strip())
                                xml_item_content += f"<{tag_name}>{escaped_td_text}</{tag_name}>"
                    if xml_item_content:
                        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><body><items><item>{xml_item_content}</item></items></body></response>'

                elif tab_name == "추가이미지":
                    try:
                        first_image_locator = tab_content_locator.locator("img").first
                        await expect(first_image_locator).to_have_attribute("src", re.compile(r"^http"), timeout=15000)
                        
                        image_urls = []
                        images = await tab_content_locator.locator("img").all()
                        for img in images:
                            src = await img.get_attribute("src")
                            if src and src.startswith('http'):
                                image_urls.append(src)
                        
                        unique_urls = list(dict.fromkeys(image_urls))
                        if unique_urls:
                            xml_items = ""
                            for url in unique_urls:
                                xml_items += f"<item><originimgurl>{url}</originimgurl></item>"
                            final_xml_string = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><body><items>{xml_items}</items></body></response>'
                            print(f"DEBUG SCRAPER: Returning XML for 추가이미지: {final_xml_string}")
                            return final_xml_string
                    except Exception as e:
                        print(f"DEBUG SCRAPER: Error while waiting for/scraping images: {e}")
                        return "<response><body><items></items></body></response>"

            except Exception:
                return "<response><body><items></items></body></response>"
            
            return "<response><body><items></items></body></response>"

    except Exception as e:
        await page.screenshot(path=f"debug_xml_error.png")
        raise e
    finally:
        await _close_page_context(p, browser)

async def get_available_tabs(params):
    p, browser, page = await _get_page_context()
    try:
        await _navigate_to_results_page(page, **{k: v for k, v in params.items() if k in ['language', 'province', 'sigungu', 'tourism_type', 'cat1', 'cat2', 'cat3']})
        if params.get("pageNo", 1) > 1:
            await _go_to_page(page, params["pageNo"])

        await page.wait_for_function("document.querySelector('textarea#ResponseXML').value.length > 10", timeout=15000)
        
        xml_content = await page.locator("textarea#ResponseXML").input_value()
        root = ET.fromstring(xml_content)
        items = root.findall('.//body/items/item')
        item_to_click = next((item for item in items if item.findtext('contentid') == params.get('contentid')), None)

        if item_to_click is None:
            raise Exception(f"Could not find item with contentid '{params.get('contentid')}' on page {params.get('pageNo', 1)}.")

        title_to_click = item_to_click.findtext('title')
        
        await page.locator(f'ul.gallery-list li:has-text("{title_to_click}")').click()
        
        await page.wait_for_selector('div.tab-box ul.tab-type2', timeout=10000)
        tab_texts = await page.locator('div.tab-box ul.tab-type2 li button').all_text_contents()
        
        available_tabs = [tab.strip() for tab in tab_texts if tab.strip()]
        
        if not available_tabs:
            return ["공통정보"]

        return available_tabs
    except Exception as e:
        print(f"DEBUG: Error in get_available_tabs, returning default tabs. Error: {e}")
        return ["공통정보", "소개정보", "반복정보", "추가이미지"]
    finally:
        await _close_page_context(p, browser)


# Functions for dropdowns are self-contained and do not need changes
async def get_sigungu_options(province):
    if not province or province == "전국": return []
    p, browser, page = await _get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("지역 선택")').click()
        await page.wait_for_selector('div.modal.region-modal.on', timeout=5000)
        await page.locator(f'div.modal.region-modal.on a[name="areaCd"]:has-text("{province}")').click()
        await page.wait_for_timeout(1000)
        sigungu_names = await page.locator('div.modal.region-modal.on a[name="signguCd"]').all_text_contents()
        return [name.strip() for name in sigungu_names if name.strip()]
    finally:
        await _close_page_context(p, browser)

async def get_large_category_options(tourism_type):
    if not tourism_type: return []
    p, browser, page = await _get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("관광타입 선택")').click()
        await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        category_names = await page.locator('div.modal#popup1.on a[name="cat1"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await _close_page_context(p, browser)

async def get_medium_category_options(tourism_type, large_category):
    if not tourism_type or not large_category: return []
    p, browser, page = await _get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("관광타입 선택")').click()
        await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{large_category}")').click()
        await page.wait_for_timeout(500)
        category_names = await page.locator('div.modal#popup1.on a[name="cat2"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await _close_page_context(p, browser)

async def get_small_category_options(tourism_type, large_category, medium_category):
    if not tourism_type or not large_category or not medium_category: return []
    p, browser, page = await _get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("관광타입 선택")').click()
        await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{large_category}")').click()
        await page.wait_for_timeout(500)
        await page.locator(f'div.modal#popup1.on a[name="cat2"]:has-text("{medium_category}")').click()
        await page.wait_for_timeout(500)
        category_names = await page.locator('div.modal#popup1.on a[name="cat3"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await _close_page_context(p, browser)