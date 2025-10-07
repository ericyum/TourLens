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
LOCATION_BASE_URL = "https://api.visitkorea.or.kr/#/useInforLocation" # 내주변 관광정보 URL 추가
LANGUAGE_MAP = {
    "한국어": "Kor", "영어": "Eng", "일어": "Jpn", "중국어(간체)": "Chs",
    "중국어(번체)": "Cht", "독일어": "Ger", "프랑스어": "Fre", "스페인어": "Spa", "러시아어": "Rus",
}

# --- Playwright Context Management ---
async def get_page_context():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    page.set_default_timeout(60000)
    return p, browser, page

async def close_page_context(p, browser):
    if browser and browser.is_connected():
        await browser.close()

# --- Common Navigation & Scraping Logic ---

async def go_to_page(page: Page, target_page: int, total_pages: int = 0):
    target_page = int(target_page)
    if target_page <= 1:
        try:
            await page.wait_for_function("() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>1</pageNo>')", timeout=15000)
        except Exception:
            # Initial search might not be page 1 if there are no results, so don't fail here.
            pass
        return

    # Determine initial direction
    go_backwards = total_pages > 0 and target_page > total_pages / 2

    if go_backwards:
        current_page_text = await page.locator("div.paging button.on").get_attribute('value')
        if int(current_page_text) != total_pages:
            old_xml = await page.locator("textarea#ResponseXML").input_value()
            last_button = page.locator('div.paging button[name="last"]')
            if await last_button.is_visible():
                await last_button.click()
                await page.wait_for_function("(oldXml) => document.querySelector('textarea#ResponseXML').value !== oldXml", arg=old_xml, timeout=15000)

    # Main navigation loop
    for _ in range(3000): # Greatly increased loop limit
        current_page_loc = page.locator("div.paging button.on")
        current_page = int(await current_page_loc.get_attribute('value'))

        if current_page == target_page:
            await page.wait_for_function(f"() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>{current_page}</pageNo>')", timeout=15000)
            return # Success

        visible_buttons = await page.locator("div.paging button[value]").all()
        visible_pages = [int(await b.get_attribute('value')) for b in visible_buttons if (await b.get_attribute('value')).isdigit()]

        button_to_click = None

        if target_page in visible_pages:
            button_to_click = page.locator(f"div.paging button[value='{target_page}']")
        else:
            if go_backwards:
                if not visible_pages or target_page < min(visible_pages):
                    button_to_click = page.locator('div.paging button[name="prev"]')
                else:
                    button_to_click = page.locator(f"div.paging button[value='{min(visible_pages)}']")
            else:
                if not visible_pages or target_page > max(visible_pages):
                    button_to_click = page.locator('div.paging button[name="next"]')
                else:
                    button_to_click = page.locator(f"div.paging button[value='{max(visible_pages)}']")

        if not button_to_click or not await button_to_click.is_visible():
             raise Exception(f"Pagination logic failed: could not find a button to click to reach page {target_page}.")

        old_xml = await page.locator("textarea#ResponseXML").input_value()
        try:
            await button_to_click.click()
            await page.wait_for_function(
                "(oldXml) => document.querySelector('textarea#ResponseXML').value !== oldXml",
                arg=old_xml,
                timeout=15000
            )
        except Exception as e:
            raise Exception(f"A pagination click failed to update content. Target: {target_page}, Current: {current_page}") from e

    raise Exception(f"Failed to navigate to page {target_page} after 3000 attempts.")

async def scrape_item_detail_xml(page: Page, params):
    try:
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

        item_locator = page.locator(f'ul.gallery-list li:has-text("{title_to_click}")')

        # 상세 정보 조회를 위한 API 응답을 기다립니다.
        api_url_pattern = "/KorService2/detailCommon2"
        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=30000
        ) as response_info:
            await item_locator.click()
        
        response = await response_info.value
        detail_xml_content = await response.text()

        # 이후 로직이 정상 동작하도록 textarea의 값을 JS로 직접 설정하여 강제로 변경합니다.
        await page.locator("textarea#ResponseXML").evaluate("(el, content) => el.value = content", detail_xml_content)

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
                            return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response><body><items>{xml_items}</items></body></response>'
                    except Exception as e:
                        print(f"DEBUG SCRAPER: Error while waiting for/scraping images: {e}")
                        return "<response><body><items></items></body></response>"

            except Exception:
                return "<response><body><items></items></body></response>"
            
            return "<response><body><items></items></body></response>"

    except Exception as e:
        await page.screenshot(path=f"debug_xml_error.png")
        raise e
