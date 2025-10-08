import gradio as gr
import math
import os
import tempfile
import re
import pandas as pd
import xml.etree.ElementTree as ET
from playwright.async_api import expect

# Relative imports from within the same module
from . import scraper
from .common import parse_xml_to_ordered_list, BASE_URL


async def export_details_to_csv(search_params, progress=gr.Progress(track_tqdm=True)):
    """[수정됨] 가장 안정적인 방식으로, 모든 아이템을 개별적으로 처음부터 다시 검색하여 처리합니다."""
    ITEMS_PER_PAGE = 12
    TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Temp")
    os.makedirs(TEMP_DIR, exist_ok=True)

    initial_params = search_params.copy()
    if initial_params.get("sigungu") == "전체": initial_params["sigungu"] = None
    if initial_params.get("cat1") == "선택 안함": initial_params["cat1"] = None
    if initial_params.get("cat2") == "선택 안함": initial_params["cat2"] = None
    if initial_params.get("cat3") == "선택 안함": initial_params["cat3"] = None

    p, browser, page = await scraper.get_page_context()
    
    # --- 1. 전체 아이템 목록을 한 번만 가져옵니다. ---
    all_items_to_process = []
    try:
        progress(0, desc="Fetching the complete list of items...")
        total_count = await scraper.perform_initial_search_for_export(page, **initial_params)
        if total_count == 0:
            gr.Info("No items to export.")
            return None
        
        total_pages = math.ceil(total_count / ITEMS_PER_PAGE)
        for page_num in range(1, total_pages + 1):
            items_on_page = await scraper.get_items_from_page(page, page_num, total_pages)
            for item in items_on_page:
                all_items_to_process.append((item.get("contentid"), page_num, item.get("initial_item_xml")))
    except Exception as e:
        gr.Error(f"Failed to create the initial item list. Error: {e}")
        await scraper.close_page_context(p, browser)
        return None

    # --- 2. 각 아이템을 개별적으로, 처음부터 다시 검색하여 처리합니다. ---
    all_attraction_details = []
    simple_search_keys, common_info_keys, intro_info_keys, repeat_info_keys, image_keys = [], [], [], [], []
    seen_keys = set()
    
    def add_key(key, key_list):
        if key not in seen_keys:
            seen_keys.add(key)
            key_list.append(key)

    tabs_to_fetch = [
        ("공통정보", common_info_keys),
        ("소개정보", intro_info_keys),
        ("반복정보", repeat_info_keys),
        ("추가이미지", image_keys)
    ]

    try:
        for content_id, page_num, initial_xml in progress.tqdm(all_items_to_process, desc="Collecting details for each item"):
            if not content_id:
                continue

            try:
                # [ULTRA ROBUST] 매번 처음부터 검색을 다시 수행하여 완전한 독립 상태를 보장합니다.
                await page.goto(BASE_URL, timeout=60000)
                await scraper.perform_initial_search_for_export(page, **initial_params)
                await scraper.go_to_page(page, page_num, total_pages)

                combined_details = {}
                if initial_xml:
                    try:
                        root = ET.fromstring(f'<root>{initial_xml}</root>')
                        simple_item_element = root.find('item')
                        if simple_item_element is not None:
                            for child in simple_item_element:
                                if child.text and child.text.strip():
                                    add_key(child.tag, simple_search_keys)
                                    combined_details[child.tag] = child.text.strip()
                    except ET.ParseError:
                        print(f"Could not parse initial_item_xml for {content_id}")

                # 아이템 클릭
                item_to_click = page.locator(f"a:has(strong[name='{content_id}'])")
                await expect(item_to_click).to_be_visible(timeout=60000)
                await item_to_click.click()
                
                # 상세 정보 로드 확인
                xml_textarea_locator = page.locator("textarea#ResponseXML")
                await expect(xml_textarea_locator).to_have_value(re.compile(f"<contentid>{content_id}</contentid>"), timeout=60000)

                # 탭을 돌며 정보 스크래핑
                for tab_name, key_list in tabs_to_fetch:
                    xml_string = ""
                    if tab_name == "공통정보":
                        xml_string = await xml_textarea_locator.input_value()
                    else:
                        tab_button = page.locator(f'button:has-text("{tab_name}")')
                        if await tab_button.is_visible():
                            initial_xml_before_click = await xml_textarea_locator.input_value()
                            await tab_button.click()
                            try:
                                await scraper.wait_for_xml_update(page, initial_xml_before_click)
                                xml_string = await xml_textarea_locator.input_value()
                            except Exception:
                                pass
                    
                    item_details_list = parse_xml_to_ordered_list(xml_string)
                    if tab_name == "추가이미지":
                        image_urls = [val for key, val in item_details_list if key == 'originimgurl']
                        for i, url in enumerate(image_urls[:5]):
                             img_key = f'image_url_{i+1}'
                             add_key(img_key, key_list)
                             combined_details[img_key] = url
                    else:
                        for key, value in item_details_list:
                            original_key = key
                            counter = 1
                            while key in combined_details:
                                counter += 1
                                key = f"{original_key}_{counter}"
                            add_key(key, key_list)
                            combined_details[key] = value

                all_attraction_details.append(combined_details)

            except Exception as e:
                print(f"Failed to process contentid '{content_id}' on page {page_num}. Error: {e}. Skipping item.")
                continue
    finally:
        await scraper.close_page_context(p, browser)

    if not all_attraction_details:
        gr.Info("No details could be collected.")
        return None

    progress(0.9, desc="Creating CSV file with specified order...")
    
    final_ordered_columns = simple_search_keys + common_info_keys + intro_info_keys + repeat_info_keys + image_keys
    
    df = pd.DataFrame(all_attraction_details)
    
    existing_cols = [col for col in final_ordered_columns if col in df.columns]
    df = df.reindex(columns=existing_cols).fillna('')

    if 'homepage' in df.columns:
        df['homepage'] = df['homepage'].apply(lambda x: re.search(r'href=["\\](.*?)["\\]', str(x)).group(1) if x and isinstance(x, str) and re.search(r'href=["\\](.*?)["\\]', x) else x)

    try:
        with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.csv', prefix='tour_details_all_', encoding='utf-8-sig') as temp_f:
            df.to_csv(temp_f.name, index=False)
            gr.Info("CSV file with all items has been created successfully.")
            return temp_f.name
    except Exception as e:
        gr.Error(f"Error saving CSV file: {e}")
        return None
