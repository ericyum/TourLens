import gradio as gr
import math
import os
import tempfile
import re
import pandas as pd
import xml.etree.ElementTree as ET
from playwright.async_api import expect
import datetime

# Relative imports from within the same module
from . import scraper
from .common import parse_xml_to_ordered_list, wait_for_xml_update

async def export_details_to_csv(search_params, progress=gr.Progress(track_tqdm=True)):
    """[최종 수정 4] 사용자의 요청에 따라 상세한 로그와 스크린샷 피드백 기능을 추가한 버전입니다."""
    
    # --- 0. 설정 및 피드백 디렉토리 생성 ---
    ITEMS_PER_PAGE = 12
    all_attraction_details = []
    
    # 피드백 이미지 저장 경로 설정
    feedback_dir = os.path.join("Temp", "export_feedback")
    os.makedirs(feedback_dir, exist_ok=True)
    print(f"피드백 스크린샷은 '{feedback_dir}' 폴더에 저장됩니다.")

    def get_screenshot_path(name):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(feedback_dir, f"{timestamp}_{name}.png")

    # CSV 컬럼 순서 유지를 위한 키 리스트
    simple_search_keys, common_info_keys, intro_info_keys, repeat_info_keys = [], [], [], []
    seen_keys = set()
    def add_key(key, key_list):
        if key not in seen_keys:
            seen_keys.add(key)
            key_list.append(key)

    # --- 1. Playwright 초기화 및 초기 검색 ---
    print("CSV 내보내기 프로세스를 시작합니다.")
    initial_params = search_params.copy()
    if initial_params.get("sigungu") == "전체": initial_params["sigungu"] = None
    if initial_params.get("cat1") == "선택 안함": initial_params["cat1"] = None
    if initial_params.get("cat2") == "선택 안함": initial_params["cat2"] = None
    if initial_params.get("cat3") == "선택 안함": initial_params["cat3"] = None

    p, browser, page = await scraper.get_page_context()

    try:
        print("초기 검색을 시작합니다...")
        progress(0, desc="전체 아이템 수를 확인하는 중...")
        total_count = await scraper.perform_initial_search_for_export(page, **initial_params)
        
        if total_count == 0:
            gr.Info("내보낼 데이터가 없습니다.")
            print("내보낼 데이터가 없어 프로세스를 종료합니다.")
            return None
        
        total_pages = math.ceil(total_count / ITEMS_PER_PAGE)
        print(f"초기 검색 완료. 총 {total_count}개의 아이템, {total_pages}개의 페이지를 확인했습니다.")
        await page.screenshot(path=get_screenshot_path("01_initial_search_results.png"))

        # --- 2. 페이지 순회 (Outer Loop) ---
        for page_num in progress.tqdm(range(1, total_pages + 1), desc="페이지 처리 중"):
            print(f"\n--- {page_num} 페이지 처리를 시작합니다. ---")
            await page.screenshot(path=get_screenshot_path(f"{page_num}_00_page_start.png"))
            await scraper.go_to_page(page, page_num, total_pages)
            await expect(page.locator("ul.gallery-list")).to_be_visible(timeout=15000)
            print(f"{page_num} 페이지로 이동 완료.")
            await page.screenshot(path=get_screenshot_path(f"{page_num}_01_page_loaded.png"))
            
            items_on_this_page_data = await scraper.get_items_from_page(page, page_num, total_pages)
            item_count_on_page = len(items_on_this_page_data)
            print(f"{page_num} 페이지에서 {item_count_on_page}개의 아이템을 확인했습니다.")

            # --- 3. 페이지 내 아이템 순회 (Inner Loop) ---
            for i in range(item_count_on_page):
                current_item_locator = page.locator("ul.gallery-list > li > a").nth(i)
                content_id = await current_item_locator.locator("strong[name]").get_attribute("name")
                print(f"  [{i+1}/{item_count_on_page}] 콘텐츠 ID '{content_id}' 처리를 시작합니다.")

                try:
                    # --- 4. 아이템 클릭 및 상세 정보 스크래핑 ---
                    await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_before_click.png"))
                    await expect(current_item_locator).to_be_visible(timeout=10000)
                    await current_item_locator.click()
                    print(f"    '{content_id}' 클릭 완료. 상세 정보 로딩을 기다립니다...")

                    xml_textarea_locator = page.locator("textarea#ResponseXML")
                    await expect(xml_textarea_locator).to_have_value(re.compile(f"<contentid>{content_id}</contentid>"), timeout=30000)
                    print("    상세 정보 로딩 완료.")
                    await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_after_click_details_loaded.png"))

                    combined_details = {}
                    xml_sources = {}
                    tabs_to_scrape = [("공통정보", common_info_keys), ("소개정보", intro_info_keys), ("반복정보", repeat_info_keys)]

                    # 공통정보
                    print("    - 공통정보 수집 중...")
                    xml_sources["공통정보"] = await xml_textarea_locator.input_value()

                    # 소개정보, 반복정보
                    for tab_name, _ in tabs_to_scrape[1:]:
                        print(f"    - {tab_name} 탭 확인 중...")
                        tab_locator = page.locator(f'button:has-text("{tab_name}")')
                        
                        if await tab_locator.is_visible():
                            print(f"    - {tab_name} 탭으로 이동 및 정보 수집 중...")
                            initial_xml = await xml_textarea_locator.input_value()
                            await tab_locator.click()
                            await wait_for_xml_update(page, initial_xml)
                            xml_sources[tab_name] = await xml_textarea_locator.input_value()
                            await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_tab_{tab_name}.png"))
                        else:
                            print(f"    - {tab_name} 탭이 없어 건너뜁니다.")

                    print("    모든 탭 정보 수집 완료. 공통정보 탭으로 복귀합니다.")
                    await page.locator('button:has-text("공통정보")').click()

                    # --- 5. 수집된 모든 XML 파싱 ---
                    initial_item_xml = next((item['initial_item_xml'] for item in items_on_this_page_data if item['contentid'] == content_id), None)
                    if initial_item_xml:
                        root = ET.fromstring(f"<root>{initial_item_xml}</root>")
                        simple_item_element = root.find('item')
                        if simple_item_element is not None:
                            for child in simple_item_element:
                                if child.text and child.text.strip():
                                    add_key(child.tag, simple_search_keys)
                                    combined_details[child.tag] = child.text.strip()

                    for tab_name, key_list in tabs_to_scrape:
                        item_details_list = parse_xml_to_ordered_list(xml_sources.get(tab_name, ""))
                        for key, value in item_details_list:
                            original_key = key
                            counter = 1
                            while key in combined_details:
                                counter += 1
                                key = f"{original_key}_{counter}"
                            add_key(key, key_list)
                            combined_details[key] = value
                    all_attraction_details.append(combined_details)
                    print("    XML 파싱 및 데이터 저장 완료.")

                    # --- 6. 목록으로 돌아가기 ---
                    print("    목록 페이지로 돌아갑니다...")
                    await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_before_goback.png"))
                    await page.go_back()
                    await page.wait_for_load_state('networkidle', timeout=15000)
                    await expect(page.locator("ul.gallery-list")).to_be_visible(timeout=30000)
                    await expect(page.locator("div.paging")).to_be_visible(timeout=10000)
                    print("    목록 페이지로 복귀 완료.")
                    await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_after_goback.png"))

                except Exception as e:
                    print(f"콘텐츠 ID '{content_id}' 처리 중 오류 발생: {e}. 다음 항목으로 넘어갑니다.")
                    await page.screenshot(path=get_screenshot_path(f"{page_num}_{i+1}_error.png"))
                    try:
                        await page.go_back()
                        await expect(page.locator("ul.gallery-list")).to_be_visible(timeout=15000)
                    except Exception as recovery_e:
                        print(f"복구 실패: {recovery_e}. 현재 페이지를 다시 로드합니다.")
                        await scraper.go_to_page(page, page_num, total_pages)
                    continue

    finally:
        print("\n모든 페이지 처리를 완료했습니다. 브라우저를 닫습니다.")
        await scraper.close_page_context(p, browser)

    # --- 7. CSV 파일 생성 ---
    if not all_attraction_details:
        gr.Info("수집된 상세 정보가 없습니다.")
        print("수집된 정보가 없어 CSV 파일을 생성하지 않습니다.")
        return None

    print("수집된 데이터를 CSV 파일로 변환합니다...")
    progress(0.9, desc="CSV 파일 생성 중...")
    final_ordered_columns = simple_search_keys + common_info_keys + intro_info_keys + repeat_info_keys
    df = pd.DataFrame(all_attraction_details)
    existing_cols = [col for col in final_ordered_columns if col in df.columns]
    df = df.reindex(columns=existing_cols).fillna('')

    if 'homepage' in df.columns:
        df['homepage'] = df['homepage'].apply(lambda x: re.search(r'href=["\\](.*?)["\\]', str(x)).group(1) if x and isinstance(x, str) and re.search(r'href=["\\](.*?)["\\]', x) else x)

    try:
        with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.csv', prefix='tour_details_all_', encoding='utf-8-sig') as temp_f:
            df.to_csv(temp_f.name, index=False)
            gr.Info("모든 항목에 대한 CSV 파일이 성공적으로 생성되었습니다.")
            print(f"CSV 파일이 성공적으로 생성되었습니다: {temp_f.name}")
            return temp_f.name
    except Exception as e:
        gr.Error(f"CSV 파일 저장 오류: {e}")
        print(f"CSV 파일 저장 중 오류 발생: {e}")
        return None
