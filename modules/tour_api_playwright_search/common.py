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
    page.set_default_timeout(300000)
    return p, browser, page

async def close_page_context(p, browser):
    if browser and browser.is_connected():
        await browser.close()

# --- Common Navigation & Scraping Logic ---

async def go_to_page(page: Page, target_page: int, total_pages: int = 0):
    target_page = int(target_page)
    
    # [수정] 현재 페이지 확인 로직 강화
    try:
        current_page_loc = page.locator("div.paging button.on")
        current_page = int(await current_page_loc.get_attribute('value'))
        if current_page == target_page:
            # 페이지는 맞지만, XML이 로드되기 전일 수 있으므로 확실히 대기
            await page.wait_for_function(f"() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>{target_page}</pageNo>')", timeout=5000)
            return
    except Exception:
        # 버튼이 없는 등 예외 상황 시 일단 진행
        pass
        
    if target_page <= 1:
        try:
            # 1페이지로 가는 확실한 방법: 첫 페이지 버튼 클릭
            first_button = page.locator('div.paging button[name="first"]')
            if await first_button.is_visible():
                old_xml = await page.locator("textarea#ResponseXML").input_value()
                await first_button.click()
                await page.wait_for_function("(oldXml) => document.querySelector('textarea#ResponseXML').value !== oldXml", arg=old_xml, timeout=0)
        except Exception:
             # 버튼이 없으면 이미 1페이지일 가능성이 높음
            pass
        await page.wait_for_function("() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>1</pageNo>')", timeout=5000)
        return

    # [수정] 페이지 이동 로직 최적화
    for _ in range(50): # 시도 횟수 줄임
        current_page_loc = page.locator("div.paging button.on")
        current_page = int(await current_page_loc.get_attribute('value'))

        if current_page == target_page:
            await page.wait_for_function(f"() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>{current_page}</pageNo>')", timeout=5000)
            return

        visible_buttons = await page.locator("div.paging button[value]").all()
        visible_pages = [int(await b.get_attribute('value')) for b in visible_buttons if (await b.get_attribute('value')).isdigit()]
        
        button_to_click = None
        
        if target_page in visible_pages:
            button_to_click = page.locator(f"div.paging button[value='{target_page}']")
        else:
            # 페이지 점프 로직 ('다음' 또는 '이전' 그룹 버튼 클릭)
            if target_page > current_page:
                button_to_click = page.locator('div.paging button[name="next"]')
            else:
                button_to_click = page.locator('div.paging button[name="prev"]')

        if not button_to_click or not await button_to_click.is_visible():
             raise Exception(f"Pagination logic failed: could not find a button to click to reach page {target_page}.")

        old_xml = await page.locator("textarea#ResponseXML").input_value()
        try:
            await button_to_click.click()
            await page.wait_for_function(
                "(oldXml) => document.querySelector('textarea#ResponseXML').value !== oldXml",
                arg=old_xml,
                timeout=0
            )
        except Exception as e:
            raise Exception(f"A pagination click failed to update content. Target: {target_page}, Current: {current_page}") from e

    raise Exception(f"Failed to navigate to page {target_page} after 50 attempts.")


# [수정됨] 이 함수는 이제 현재 페이지에 아이템이 있다고 가정하고 동작함
async def scrape_item_detail_xml(page: Page, params):
    try:
        # 현재 페이지의 XML을 다시 읽어옴
        await page.wait_for_function(f"() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>{params.get('pageNo', 1)}</pageNo>')", timeout=5000)
        xml_content = await page.locator("textarea#ResponseXML").input_value()
        root = ET.fromstring(xml_content)
        items = root.findall('.//body/items/item')

        title_to_click = None
        for item in items:
            if item.findtext('contentid') == params.get('contentid'):
                title_to_click = item.findtext('title')
                break
        
        if title_to_click is None:
            # 아이템을 못찾으면 에러 발생 (app.py에서 처리)
            raise Exception(f"Could not find item with contentid '{params.get('contentid')}' on page {params.get('pageNo', 1)}.")
        
        # [핵심 수정] 갤러리 목록에서 정확한 아이템을 클릭
        item_locator = page.locator(f'ul.gallery-list li:has(div.gallery-tit:has-text("{title_to_click}"))')
        await expect(item_locator.first).to_be_visible(timeout=5000)

        # 상세 정보 조회를 위한 API 응답을 기다립니다.
        api_url_pattern = "/KorService2/detailCommon2"
        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=0
        ) as response_info:
            await item_locator.first.click()
        
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
            await page.wait_for_function(js_function, arg=initial_xml, timeout=5000) # 타임아웃 추가
            new_xml = await xml_textarea_locator.input_value()
            if not new_xml.strip():
                 raise Exception("XML is empty, proceeding to HTML scrape.")
            return new_xml
        except Exception:
            # (이하 HTML 스크래핑 로직은 예외 처리로 유지)
            try:
                tab_name = params.get("tab_name")
                await page.locator('div.tab-content.on h4').wait_for(state='attached', timeout=5000)
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
                        await expect(first_image_locator).to_have_attribute("src", re.compile(r"^http"), timeout=5000)
                        
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
        # 에러 발생 시 스크린샷을 찍어 디버깅에 도움을 줌
        await page.screenshot(path=f"debug_scrape_error_contentid_{params.get('contentid')}.png")
        raise e