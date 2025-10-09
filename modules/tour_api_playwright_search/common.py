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
TOTAL_SEARCH_BASE_URL = "https://api.visitkorea.or.kr/#/useInforUnite"
DATE_SEARCH_BASE_URL = "https://api.visitkorea.or.kr/#/useInforDate"
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

# [수정됨] XML 업데이트 대기 로직 개선
async def wait_for_xml_update(page: Page, old_xml: str):
    """Waits for the ResponseXML textarea to update with new, non-empty content."""
    await page.wait_for_function(
        """(oldXml) => {
            const el = document.querySelector('textarea#ResponseXML');
            return el && el.value !== oldXml && el.value.trim().length > 0;
        }""",
        arg=old_xml,
        timeout=0
    )

# [최종 개선] 최소 클릭 페이지 이동 로직
async def go_to_page(page: Page, target_page: int, total_pages: int = 0):
    target_page = int(target_page)

    # 페이지네이션 컨트롤이 존재하는지 먼저 확인
    paging_container = page.locator("div.paging")
    if await paging_container.count() == 0:
        # 페이지네이션이 없고, 목표 페이지가 1이면 이미 도달한 상태
        if target_page == 1:
            return
        # 페이지네이션이 없는데 다른 페이지를 요청하면 오류
        else:
            raise Exception(f"Pagination controls not found, but page {target_page} was requested.")

    # 무한 루프 방지를 위한 최대 시도 횟수
    for _ in range(50):
        current_page_loc = page.locator("div.paging button.on")
        await expect(current_page_loc).to_be_visible(timeout=60000)
        current_page = int(await current_page_loc.get_attribute('value'))

        if current_page == target_page:
            await page.wait_for_function(f"() => document.querySelector('textarea#ResponseXML').value.includes('<pageNo>{target_page}</pageNo>')", timeout=60000)
            return

        # 1. 시작점 결정 (앞 절반 or 뒤 절반)
        go_backwards = total_pages > 0 and target_page > total_pages / 2
        
        # 2. 시작점으로 이동 (필요 시)
        if go_backwards:
            # 목표가 마지막 페이지 근처인데 현재는 앞쪽에 있을 경우, 맨 끝으로 점프
            if current_page < total_pages / 2:
                old_xml = await page.locator("textarea#ResponseXML").input_value()
                await page.locator('div.paging button[name="last"]').click()
                await wait_for_xml_update(page, old_xml)
                # 재탐색을 위해 루프의 처음으로 돌아감
                continue 
        else:
            # 목표가 첫 페이지 근처인데 현재는 뒤쪽에 있을 경우, 맨 처음으로 점프
             if current_page > total_pages / 2:
                old_xml = await page.locator("textarea#ResponseXML").input_value()
                await page.locator('div.paging button[name="first"]').click()
                await wait_for_xml_update(page, old_xml)
                continue

        # 3. 현재 보이는 페이지 번호들 확인
        visible_buttons = await page.locator("div.paging button[value]").all()
        visible_pages = [int(await b.get_attribute('value')) for b in visible_buttons if (await b.get_attribute('value') or "").isdigit()]

        # 4. 전략적 이동
        old_xml = await page.locator("textarea#ResponseXML").input_value()
        
        # 4a. 목표 페이지가 보이면 바로 클릭
        if target_page in visible_pages:
            await page.locator(f"div.paging button[value='{target_page}']").click()
        # 4b. 목표 페이지가 현재 블록보다 뒤에 있으면
        elif target_page > current_page:
            # 페이지 블록 이동이 필요하면 다음 버튼 클릭
            if target_page > max(visible_pages):
                await page.locator('div.paging button[name="next"]').click()
            # 그렇지 않고, 현재 페이지가 블록의 마지막이 아니면, 블록의 마지막으로 점프
            elif max(visible_pages) != current_page:
                await page.locator(f"div.paging button[value='{max(visible_pages)}']").click()
            # 현재 페이지가 블록의 마지막이면 다음 버튼 클릭
            else:
                 await page.locator('div.paging button[name="next"]').click()

        # 4c. 목표 페이지가 현재 블록보다 앞에 있으면
        else: # target_page < current_page
            # 페이지 블록 이동이 필요하면 이전 버튼 클릭
            if target_page < min(visible_pages):
                await page.locator('div.paging button[name="prev"]').click()
            # 그렇지 않고, 현재 페이지가 블록의 시작이 아니면, 블록의 시작으로 점프
            elif min(visible_pages) != current_page:
                await page.locator(f"div.paging button[value='{min(visible_pages)}']").click()
            # 현재 페이지가 블록의 시작이면 이전 버튼 클릭
            else:
                await page.locator('div.paging button[name="prev"]').click()

        await wait_for_xml_update(page, old_xml)

    raise Exception(f"Failed to navigate to page {target_page} after 50 attempts.")


# [최종] 상세 정보 로직 단순화
async def scrape_item_detail_xml(page: Page, params):
    try:
        gallery_container = page.locator("ul.gallery-list")
        await expect(gallery_container).to_be_visible(timeout=60000)
        await expect(gallery_container.locator("li").first).to_be_visible(timeout=60000)

        xml_content = await page.locator("textarea#ResponseXML").input_value()
        root = ET.fromstring(xml_content)
        items = root.findall('.//body/items/item')

        title_to_click = None
        for item in items:
            if item.findtext('contentid') == params.get('contentid'):
                title_to_click = item.findtext('title')
                break
        
        if title_to_click is None:
            raise Exception(f"Could not find item with contentid '{params.get('contentid')}' on page {params.get('pageNo', 1)}.")
        
        item_to_click = page.get_by_role("listitem").filter(has_text=re.compile(f"^{re.escape(title_to_click)}$"))
        await expect(item_to_click.first).to_be_visible(timeout=60000)

        api_url_pattern = "/KorService2/detailCommon2"
        async with page.expect_response(
            lambda response: api_url_pattern in response.url and response.status == 200,
            timeout=0
        ) as response_info:
            await item_to_click.first.click()
        
        response = await response_info.value
        detail_xml_content = await response.text()
        
        await page.locator("textarea#ResponseXML").evaluate("(el, content) => el.value = content", detail_xml_content)

        xml_textarea_locator = page.locator("textarea#ResponseXML")
        
        requested_tab = params.get("tab_name")

        # "공통정보" 탭은 이미 로드되었으므로 바로 반환
        if requested_tab == "공통정보":
            return await xml_textarea_locator.input_value()

        # 다른 탭들은 클릭 후 XML 갱신을 기다림
        tab_button_locator = page.locator(f'button:has-text("{requested_tab}")')
        
        if not await tab_button_locator.is_visible():
            return "<response><body><items></items></body></response>"

        # 현재(공통정보) XML 내용을 저장
        initial_xml = await xml_textarea_locator.input_value()
        # 탭 버튼 클릭
        await tab_button_locator.click()
        
        try:
            # XML 내용이 바뀔 때까지 대기
            await wait_for_xml_update(page, initial_xml)
            # 바뀐 XML 내용을 반환
            return await xml_textarea_locator.input_value()
        except Exception:
            # 탭을 눌렀는데도 XML이 갱신되지 않으면(데이터가 없거나 오류), 빈 응답 반환
            return "<response><body><items><totalCount>0</totalCount></items></body></response>"

    except Exception as e:
        await page.screenshot(path=f"debug_scrape_error_contentid_{params.get('contentid')}.png")
        raise e
    finally:
        # [수정됨] 다음 작업을 위해 상태를 초기화하는 로직을 더욱 안정적으로 강화
        try:
            common_info_button = page.locator('button:has-text("공통정보")')
            # 5초간 버튼이 나타나는지 확인
            if await common_info_button.is_visible(timeout=5000):
                # 버튼의 부모 li 태그를 찾아 'on' 클래스가 있는지 확인 (이미 선택된 상태인지)
                parent_li = common_info_button.locator("xpath=..")
                class_attribute = await parent_li.get_attribute('class') or ''
                
                # '공통정보'가 이미 선택된 상태('on')가 아니라면 클릭하여 상태 초기화
                if 'on' not in class_attribute:
                    initial_xml = await page.locator("textarea#ResponseXML").input_value()
                    await common_info_button.click(timeout=5000)
                    # 상태가 실제로 초기화될 때까지(XML이 바뀔 때까지) 기다림
                    await wait_for_xml_update(page, initial_xml)
        except Exception:
            # 이 작업은 정리 목적이므로, 실패하더라도 전체 프로세스에 영향을 주지 않고 무시하고 넘어갑니다.
            pass

def parse_xml_to_dict(xml_string: str) -> dict:
    """Parses an XML string from the API into a flat dictionary."""
    if not xml_string or "<error>" in xml_string or not xml_string.strip().startswith('<?xml'):
        return {}
    try:
        root = ET.fromstring(xml_string)
        item_element = root.find('.//body/items/item')
        if item_element is None:
            return {}
        
        details = {}
        for child in item_element:
            if child.text and child.text.strip():
                clean_text = re.sub(r'<.*?>', '', child.text)
                details[child.tag] = clean_text.strip()
        return details
    except (ET.ParseError, TypeError):
        return {}

def parse_xml_to_ordered_list(xml_string: str) -> list[tuple[str, str]]:
    """Parses an XML string from the API into an ordered list of (key, value) tuples."""
    # [수정] 여러 아이템을 처리할 수 있도록 개선
    if not xml_string or "<error>" in xml_string or not xml_string.strip().startswith('<?xml'):
        return []
    try:
        root = ET.fromstring(xml_string)
        items = root.findall('.//body/items/item')
        if not items:
            return []
        
        details = []
        # '추가이미지'와 같이 여러 아이템이 오는 경우
        if len(items) > 1 and any(item.find('originimgurl') is not None for item in items):
            for item in items:
                url = item.findtext('originimgurl')
                if url:
                    details.append(('originimgurl', url))
        # '반복정보'나 '소개정보'와 같이 여러 정보가 오는 경우
        elif len(items) > 1 and any(item.find('infoname') is not None for item in items):
             for item in items:
                infoname = item.findtext('infoname')
                infotext = item.findtext('infotext')
                if infoname and infotext:
                     details.append((infoname, infotext))
        # '공통정보'와 같이 단일 아이템인 경우
        else:
            item_element = items[0]
            for child in item_element:
                if child.text and child.text.strip():
                    clean_text = re.sub(r'<.*?>', '', child.text)
                    details.append((child.tag, clean_text.strip()))
        return details
    except (ET.ParseError, TypeError):
        return []
