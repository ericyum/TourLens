import gradio as gr
import os
from dotenv import load_dotenv
import glob
import math
import json
import pandas as pd
import tempfile

# .env 파일을 최상단에서 로드
load_dotenv()

# --- 시작 시 임시 이미지 폴더 정리 ---
image_temp_dir = "image_temp"
if os.path.exists(image_temp_dir):
    files_to_delete = glob.glob(os.path.join(image_temp_dir, '*.png'))
    for f in files_to_delete:
        try:
            os.remove(f)
        except OSError as e:
            print(f"Error removing file {f}: {e}")

# --- 모듈에서 기능들을 가져옴 ---
from modules.location_search.location import get_location_js
from modules.location_search.search import find_nearby_places
from modules.area_search.controls import (
    AREA_CODES, CONTENT_TYPE_CODES, update_sigungu_dropdown
)
from modules.area_search.search import update_page_view
from modules.area_search.details import get_details
from modules.area_search.export import export_to_csv
from modules.trend_analyzer.trend_analyzer import (
    generate_trends_from_area_search,
    generate_trends_from_location_search,
    analyze_single_item,
    analyze_trends_for_titles
)
# 서울 관광 API 모듈
from modules.seoul_search.seoul_api import get_all_seoul_data
# 네이버 검색 모듈
from modules.naver_search.search import search_naver_reviews_and_scrape, summarize_blog_contents_stream, answer_question_from_reviews_stream
# Tour API 직접 조회 모듈
from modules.tour_api_playwright_search import scraper
import asyncio
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import requests
import re
# [추가됨] CSV 저장을 위한 playwright expect 임포트
from playwright.async_api import expect


# --- 서울시 관광 정보 검색 UI 및 기능 ---

ROWS_PER_PAGE = 10
PAGE_WINDOW_SIZE = 5

# 카테고리 이름과 태그 키워드 매핑
CATEGORY_TO_KEYWORDS = {
    "관광지": ["관광", "명소", "유적"],
    "문화시설": ["문화", "미술관", "박물관", "전시", "갤러리", "도서관"],
    "행사/공연/축제": ["행사", "공연", "축제", "페스티벌"],
    "여행코스": ["여행코스", "도보", "산책", "둘레길"],
    "레포츠": ["레포츠", "스포츠", "공원", "체육"],
    "숙박": ["숙박", "호텔", "모텔", "게스트하우스", "펜션"],
    "쇼핑": ["쇼핑", "백화점", "시장", "면세점"],
    "음식점": ["음식점", "맛집", "식당", "카페"],
}

def create_seoul_search_ui():
    """서울시 관광정보 API용 UI 탭 (모든 기능 포함)"""
    with gr.Blocks() as seoul_search_tab:
        # --- 상태 변수 ---
        filtered_data_state = gr.State([])
        current_page_state = gr.State(1)
        total_pages_state = gr.State(1)

        # --- UI 컴포넌트 ---
        gr.Markdown("### 서울시 관광지 검색 (카테고리별 필터링)")
        with gr.Row():
            category_dropdown = gr.Dropdown(label="카테고리", choices=list(CONTENT_TYPE_CODES.keys()), value="전체")
            search_btn = gr.Button("검색하기", variant="primary")
        
        with gr.Row():
            export_csv_btn = gr.Button("CSV로 내보내기")
            run_list_trend_btn = gr.Button("현재 목록 트렌드 저장하기")

        places_radio = gr.Radio(label="검색된 관광지 목록", choices=[], interactive=True)
        
        with gr.Row(visible=False) as pagination_row:
            first_page_btn = gr.Button("맨 처음", interactive=False)
            prev_page_btn = gr.Button("이전", interactive=False)
            pagination_numbers = gr.Radio(choices=[], label="페이지", interactive=True, scale=2)
            next_page_btn = gr.Button("다음", interactive=False)
            last_page_btn = gr.Button("맨 끝", interactive=False)
        
        csv_file_output = gr.File(label="CSV 다운로드", interactive=False)
        status_output = gr.Textbox(label="분석 상태", interactive=False, lines=2)

        with gr.Accordion("상세 정보 및 분석 결과", open=False) as details_accordion:
            raw_json_output = gr.Textbox(label="상세 정보 (Raw JSON)", lines=10, interactive=False)
            pretty_output = gr.Markdown("### 포맷된 정보")
            trend_plot_output = gr.Image(label="검색량 트렌드", interactive=False)
            reviews_output = gr.Markdown("### 네이버 블로그 후기")

        # --- 이벤트 핸들러 ---
        search_btn.click(
            fn=perform_search,
            inputs=[category_dropdown],
            outputs=[filtered_data_state, current_page_state, status_output, csv_file_output]
        ).then(
            fn=update_seoul_page_view,
            inputs=[filtered_data_state, current_page_state],
            outputs=[
                places_radio, pagination_row, 
                first_page_btn, prev_page_btn, next_page_btn, last_page_btn, 
                pagination_numbers, total_pages_state
            ]
        )

        export_csv_btn.click(
            fn=export_seoul_data_to_csv,
            inputs=[filtered_data_state],
            outputs=[csv_file_output]
        )

        run_list_trend_btn.click(
            fn=run_seoul_list_trend_analysis,
            inputs=[filtered_data_state],
            outputs=[status_output]
        )

        page_change_triggers = [
            first_page_btn.click(lambda: 1, [], current_page_state),
            prev_page_btn.click(lambda p: p - 1, [current_page_state], current_page_state),
            next_page_btn.click(lambda p: p + 1, [current_page_state], current_page_state),
            last_page_btn.click(lambda tp: tp, [total_pages_state], current_page_state),
            pagination_numbers.select(lambda evt: int(evt.value), pagination_numbers, current_page_state)
        ]

        for trigger in page_change_triggers:
            trigger.then(
                fn=update_seoul_page_view,
                inputs=[filtered_data_state, current_page_state],
                outputs=[
                    places_radio, pagination_row, 
                    first_page_btn, prev_page_btn, next_page_btn, last_page_btn, 
                    pagination_numbers, total_pages_state
                ]
            )
        
        places_radio.change(
            fn=display_details_and_analysis,
            inputs=[places_radio, filtered_data_state],
            outputs=[raw_json_output, pretty_output, trend_plot_output, reviews_output, details_accordion]
        )

    return seoul_search_tab

def perform_search(category_name):
    all_data = get_all_seoul_data()
    if not all_data:
        gr.Warning("데이터를 가져오는 데 실패했습니다. API 상태를 확인하세요.")
        return [], 1, "", None

    if category_name == "전체":
        filtered_list = all_data
    else:
        keywords = CATEGORY_TO_KEYWORDS.get(category_name, [])
        filtered_list = [item for item in all_data if item['processed'].get('tags') and any(keyword in item['processed']['tags'] for keyword in keywords)]
    
    if not filtered_list:
        gr.Info(f"'{category_name}' 카테고리에 해당하는 데이터가 없습니다.")

    return filtered_list, 1, "", None

def update_seoul_page_view(filtered_data, page_to_go):
    if not filtered_data:
        return gr.update(choices=[], value=None), gr.update(visible=False), False, False, False, False, gr.update(choices=[], value=None), 1

    page_to_go = int(page_to_go)
    total_count = len(filtered_data)
    total_pages = math.ceil(total_count / ROWS_PER_PAGE)

    start_idx = (page_to_go - 1) * ROWS_PER_PAGE
    end_idx = start_idx + ROWS_PER_PAGE
    page_items = filtered_data[start_idx:end_idx]

    place_titles = [item['processed']['title'] for item in page_items if item.get('processed', {}).get('title')]

    half_window = PAGE_WINDOW_SIZE // 2
    start_page = max(1, page_to_go - half_window)
    end_page = min(total_pages, start_page + PAGE_WINDOW_SIZE - 1)
    if end_page - start_page + 1 < PAGE_WINDOW_SIZE:
        start_page = max(1, end_page - PAGE_WINDOW_SIZE + 1)
    page_numbers_to_show = [str(i) for i in range(start_page, end_page + 1)]

    return (
        gr.update(choices=place_titles, value=None),
        gr.update(visible=total_pages > 1),
        gr.update(interactive=page_to_go > 1),
        gr.update(interactive=page_to_go < total_pages),
        gr.update(interactive=page_to_go < total_pages),
        gr.update(interactive=page_to_go < total_pages),
        gr.update(choices=page_numbers_to_show, value=str(page_to_go)),
        total_pages
    )

def display_details_and_analysis(selected_title, filtered_data, progress=gr.Progress(track_tqdm=True)):
    if not selected_title:
        return "", "", None, "", gr.update(open=False)

    progress(0, desc="상세 정보 로딩 중...")
    selected_item = next((item for item in filtered_data if item.get('processed', {}).get('title') == selected_title), None)

    if not selected_item:
        return "{}", "정보를 찾을 수 없습니다.", None, "", gr.update(open=True)

    raw_data = selected_item.get('raw', {})
    raw_json_str = json.dumps(raw_data, indent=2, ensure_ascii=False)
    
    KEY_MAP = {
        "POST_SJ": "상호명", "NEW_ADDRESS": "새주소", "ADDRESS": "구주소",
        "CMMN_TELNO": "전화번호", "CMMN_HMPG_URL": "홈페이지", "CMMN_USE_TIME": "이용시간",
        "CMMN_BSNDE": "운영요일", "CMMN_RSTDE": "휴무일", "SUBWAY_INFO": "지하철 정보",
        "TAG": "태그", "BF_DESC": "장애인 편의시설"
    }
    
    pretty_str_lines = [f"### {raw_data.get('POST_SJ', '이름 없음')}"]
    for key, friendly_name in KEY_MAP.items():
        value = raw_data.get(key)
        if value and str(value).strip():
            cleaned_value = str(value).replace('\n', ' ').strip()
            if key == 'CMMN_HMPG_URL' and 'http' in cleaned_value:
                pretty_str_lines.append(f"**{friendly_name}**: [{cleaned_value}]({cleaned_value})")
            else:
                pretty_str_lines.append(f"**{friendly_name}**: {cleaned_value}")
    pretty_str = "\n\n".join(pretty_str_lines)

    progress(0.5, desc="트렌드 및 후기 분석 중...")
    trend_image, reviews_markdown = analyze_single_item(selected_title)
    
    progress(1, desc="완료")
    return raw_json_str, pretty_str, trend_image, reviews_markdown, gr.update(open=True)

def export_seoul_data_to_csv(filtered_data, progress=gr.Progress(track_tqdm=True)):
    """현재 필터링된 서울시 데이터를 CSV 파일로 내보냅니다."""
    if not filtered_data:
        gr.Warning("내보낼 데이터가 없습니다.")
        return None
    
    progress(0, desc="CSV 데이터 준비 중...")
    raw_data_list = [item['raw'] for item in filtered_data]
    df = pd.DataFrame(raw_data_list)

    progress(0.5, desc="CSV 파일 생성 중...")
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.csv', prefix='seoul_attractions_', encoding='utf-8-sig') as temp_f:
        df.to_csv(temp_f.name, index=False, encoding='utf-8-sig') # 인코딩 명시적으로 추가
        gr.Info("CSV 파일 생성이 완료되었습니다.")
        progress(1, desc="완료")
        return temp_f.name

def run_seoul_list_trend_analysis(filtered_data, progress=gr.Progress(track_tqdm=True)):
    """현재 필터링된 목록 전체에 대한 트렌드/후기 분석을 실행하고 파일로 저장합니다."""
    if not filtered_data:
        return "분석할 데이터가 없습니다."

    titles = [item['processed']['title'] for item in filtered_data if item.get('processed', {}).get('title')]
    if not titles:
        return "분석할 관광지 이름이 없습니다."
        
    status = analyze_trends_for_titles(titles=titles, progress=progress)
    return status


# --- 각 탭의 UI를 생성하는 함수들 ---

def create_location_search_tab():
    """'내 위치로 검색' 탭의 UI를 생성합니다."""
    with gr.Blocks() as tab:
        gr.Markdown("### 내 위치 기반 관광지 검색")
        places_info_state_nearby = gr.State({})
        with gr.Row():
            get_loc_button = gr.Button("내 위치 가져오기")
            lat_box, lon_box = gr.Textbox(label="위도", interactive=False), gr.Textbox(label="경도", interactive=False)
        
        with gr.Row():
            search_button_nearby = gr.Button("이 좌표로 주변 관광지 검색", variant="primary")
            run_trend_btn_nearby = gr.Button("현재 목록 트렌드 저장하기")

        radio_list_nearby = gr.Radio(label="관광지 목록", interactive=True)
        status_output_nearby = gr.Textbox(label="작업 상태", interactive=False)
        
        with gr.Accordion("상세 정보 보기", open=False):
            common_raw_n, common_pretty_n = gr.Textbox(label="Raw JSON"), gr.Markdown()
            intro_raw_n, intro_pretty_n = gr.Textbox(label="Raw JSON"), gr.Markdown()
            info_raw_n, info_pretty_n = gr.Textbox(label="Raw JSON"), gr.Markdown()
        
        get_loc_button.click(fn=None, js=get_location_js, outputs=[lat_box, lon_box])
        search_button_nearby.click(fn=find_nearby_places, inputs=[lat_box, lon_box], outputs=[radio_list_nearby, places_info_state_nearby])
        run_trend_btn_nearby.click(fn=generate_trends_from_location_search, inputs=places_info_state_nearby, outputs=status_output_nearby)
        radio_list_nearby.change(fn=get_details, inputs=[radio_list_nearby, places_info_state_nearby], outputs=[common_raw_n, common_pretty_n, intro_raw_n, intro_pretty_n, info_raw_n, info_pretty_n])
    return tab

def create_area_search_tab():
    """'지역/카테고리별 검색' 탭의 UI를 생성합니다."""
    with gr.Blocks() as tab:
        gr.Markdown("### 지역/카테고리 기반 관광지 검색 (TourAPI)")
        current_area = gr.State(None)
        current_sigungu = gr.State(None)
        current_category = gr.State(None)
        current_page = gr.State(1)
        total_pages = gr.State(1)
        places_info_state_area = gr.State({})

        with gr.Row():
            area_dropdown = gr.Dropdown(label="지역", choices=list(AREA_CODES.keys()))
            sigungu_dropdown = gr.Dropdown(label="시군구", interactive=False)
            category_dropdown = gr.Dropdown(label="카테고리", choices=list(CONTENT_TYPE_CODES.keys()), value="전체")
        
        with gr.Row():
            search_by_area_btn = gr.Button("검색하기", variant="primary")
            export_csv_btn = gr.Button("CSV로 내보내기")
            run_trend_btn_area = gr.Button("현재 목록 트렌드 저장하기")

        radio_list_area = gr.Radio(label="관광지 목록", interactive=True)
        
        with gr.Row(visible=False) as pagination_row:
            first_page_btn = gr.Button("<< 맨 처음")
            prev_page_btn = gr.Button("< 이전")
            page_numbers_radio = gr.Radio(label="페이지", interactive=True, scale=3)
            next_page_btn = gr.Button("다음 >")
            last_page_btn = gr.Button("맨 끝 >>")
        
        csv_file_output = gr.File(label="다운로드", interactive=False)
        status_output_area = gr.Textbox(label="작업 상태", interactive=False)

        with gr.Accordion("상세 정보 보기", open=False):
            common_raw_a, common_pretty_a = gr.Textbox(label="Raw JSON"), gr.Markdown()
            intro_raw_a, intro_pretty_a = gr.Textbox(label="Raw JSON"), gr.Markdown()
            info_raw_a, info_pretty_a = gr.Textbox(label="Raw JSON"), gr.Markdown()
        
        outputs_for_page_change = [current_area, current_sigungu, current_category, current_page, total_pages, places_info_state_area, radio_list_area, page_numbers_radio, first_page_btn, prev_page_btn, next_page_btn, last_page_btn, pagination_row]
        
        area_dropdown.change(fn=update_sigungu_dropdown, inputs=area_dropdown, outputs=sigungu_dropdown)
        search_by_area_btn.click(fn=update_page_view, inputs=[area_dropdown, sigungu_dropdown, category_dropdown, gr.Number(value=1, visible=False)], outputs=outputs_for_page_change)
        
        export_csv_btn.click(fn=export_to_csv, inputs=[area_dropdown, sigungu_dropdown, category_dropdown], outputs=csv_file_output)
        run_trend_btn_area.click(fn=generate_trends_from_area_search, inputs=[area_dropdown, sigungu_dropdown, category_dropdown], outputs=status_output_area)

        page_inputs = [current_area, current_sigungu, current_category]
        first_page_btn.click(lambda area, sigungu, cat: update_page_view(area, sigungu, cat, 1), inputs=page_inputs, outputs=outputs_for_page_change)
        prev_page_btn.click(lambda area, sigungu, cat, page: update_page_view(area, sigungu, cat, page - 1), inputs=page_inputs + [current_page], outputs=outputs_for_page_change)
        next_page_btn.click(lambda area, sigungu, cat, page: update_page_view(area, sigungu, cat, page + 1), inputs=page_inputs + [current_page], outputs=outputs_for_page_change)
        last_page_btn.click(lambda area, sigungu, cat, pages: update_page_view(area, sigungu, cat, pages), inputs=page_inputs + [total_pages], outputs=outputs_for_page_change)
        page_numbers_radio.select(update_page_view, inputs=page_inputs + [page_numbers_radio], outputs=outputs_for_page_change)

        radio_list_area.change(fn=get_details, inputs=[radio_list_area, places_info_state_area], outputs=[common_raw_a, common_pretty_a, intro_raw_a, intro_pretty_a, info_raw_a, info_pretty_a])
    return tab



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
        # '반복정보'와 같이 여러 정보가 오는 경우
        elif len(items) > 1 and any(item.find('infoname') is not None for item in items):
             for item in items:
                infoname = item.findtext('infoname')
                infotext = item.findtext('infotext')
                if infoname and infotext:
                     details.append((infoname, infotext))
        # '공통정보', '소개정보'와 같이 단일 아이템인 경우
        else:
            item_element = items[0]
            for child in item_element:
                if child.text and child.text.strip():
                    clean_text = re.sub(r'<.*?>', '', child.text)
                    details.append((child.tag, clean_text.strip()))
        return details
    except (ET.ParseError, TypeError):
        return []

# [최종 수정] CSV 내보내기 함수
async def export_details_to_csv(search_params, progress=gr.Progress(track_tqdm=True)):
    """[수정됨] 단일 브라우저 세션을 사용하여 모든 아이템의 상세 정보를 CSV로 저장합니다."""
    ITEMS_PER_PAGE = 12
    TEMP_DIR = os.path.join(os.path.dirname(__file__), "Temp")
    os.makedirs(TEMP_DIR, exist_ok=True)

    initial_params = search_params.copy()
    if initial_params.get("sigungu") == "전체": initial_params["sigungu"] = None
    if initial_params.get("cat1") == "선택 안함": initial_params["cat1"] = None
    if initial_params.get("cat2") == "선택 안함": initial_params["cat2"] = None
    if initial_params.get("cat3") == "선택 안함": initial_params["cat3"] = None

    p, browser, page = await scraper.get_page_context()
    all_items_with_page = []
    total_pages = 0
    try:
        progress(0, desc="Getting total number of items...")
        total_count = await scraper.perform_initial_search_for_export(page, **initial_params)

        if total_count == 0:
            gr.Info("No items to export.")
            await scraper.close_page_context(p, browser)
            return None
        total_pages = math.ceil(total_count / ITEMS_PER_PAGE)

        # 모든 페이지를 돌며 아이템 목록과 페이지 번호 수집
        for page_num in progress.tqdm(range(1, total_pages + 1), desc=f"Fetching item lists from {total_pages} pages"):
            try:
                results = await scraper.get_items_from_page(page, page_num, total_pages)
                for item in results:
                    all_items_with_page.append((item, page_num))
            except Exception as e:
                print(f"Warning: Failed to fetch page {page_num}. Error: {e}")
                continue
    
    except Exception as e:
        gr.Error(f"Failed during page fetching. Error: {e}")
        await scraper.close_page_context(p, browser)
        return None
    
    # 목록 수집이 끝난 후에는 브라우저를 재시작하지 않고 그대로 사용
    
    if not all_items_with_page:
        gr.Info("Could not fetch any item lists.")
        await scraper.close_page_context(p, browser)
        return None

    all_attraction_details = []
    simple_search_keys, common_info_keys, intro_info_keys, repeat_info_keys, image_keys = [], [], [], [], []
    seen_keys = set()
    
    def add_key(key, key_list):
        # 중복되지 않는 키만 순서대로 추가
        if key not in seen_keys:
            seen_keys.add(key)
            key_list.append(key)

    tabs_to_fetch = [
        ("공통정보", common_info_keys),
        ("소개정보", intro_info_keys),
        ("반복정보", repeat_info_keys),
        ("추가이미지", image_keys)
    ]
    
    current_page_in_browser = 1 # 초기 검색 후 1페이지에 있으므로
    try:
        # 상세 정보 수집 시작
        for item, page_num in progress.tqdm(all_items_with_page, desc="Collecting details for each attraction"):
            content_id = item.get("contentid")
            if not content_id: continue

            try:
                # 1. 브라우저의 현재 페이지와 아이템의 원래 페이지가 다르면 이동
                if current_page_in_browser != page_num:
                    await scraper.go_to_page(page, page_num, total_pages)
                    current_page_in_browser = page_num
                
                combined_details = {}
                # 초기 검색에서 얻은 기본 정보 추가
                initial_xml = item.get("initial_item_xml")
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

                # 2. 상세 페이지로 이동
                gallery_container = page.locator("ul.gallery-list")
                await expect(gallery_container).to_be_visible(timeout=60000)
                
                title_to_click = item.get('title')
                item_to_click = page.get_by_role("listitem").filter(has_text=re.compile(f"^{re.escape(title_to_click)}$"))
                await expect(item_to_click.first).to_be_visible(timeout=60000)
                await item_to_click.first.click()
                
                # 3. 상세 페이지 로딩 대기 (공통정보 XML 확인)
                xml_textarea_locator = page.locator("textarea#ResponseXML")
                await expect(xml_textarea_locator).to_have_value(re.compile(f"<contentid>{content_id}</contentid>"), timeout=60000)

                # 4. 모든 탭 순회하며 정보 수집
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
                                pass # XML 업데이트 실패시 xml_string은 "" 유지
                    
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

                # 5. [중요] 목록 페이지로 돌아가기
                await page.go_back()
                await expect(page.locator("ul.gallery-list")).to_be_visible(timeout=60000)


            except Exception as e:
                print(f"Error fetching details for contentid '{content_id}' on page {page_num}: {e}")
                # 복구를 위해 검색 페이지(1페이지)로 돌아감
                await scraper.perform_initial_search_for_export(page, **initial_params)
                current_page_in_browser = 1
                continue
    finally:
        await scraper.close_page_context(p, browser)


    if not all_attraction_details:
        gr.Info("No details could be collected.")
        return None

    progress(0.9, desc="Creating CSV file with specified order...")
    
    final_ordered_columns = simple_search_keys + common_info_keys + intro_info_keys + repeat_info_keys + image_keys
    
    df = pd.DataFrame(all_attraction_details)
    
    # 데이터프레임에 존재하는 컬럼만으로 순서 재정렬
    existing_cols = [col for col in final_ordered_columns if col in df.columns]
    df = df.reindex(columns=existing_cols) # reindex로 순서 맞추고 없는 컬럼은 NaN으로 채움
    df = df.fillna('') # NaN을 빈 문자열로 변환

    if 'homepage' in df.columns:
        df['homepage'] = df['homepage'].apply(lambda x: re.search(r'href=["\'](.*?)["\']', str(x)).group(1) if x and isinstance(x, str) and re.search(r'href=["\'](.*?)["\']', x) else x)

    try:
        with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.csv', prefix='tour_details_all_', encoding='utf-8-sig') as temp_f:
            df.to_csv(temp_f.name, index=False)
            gr.Info("CSV file with all items has been created successfully.")
            return temp_f.name
    except Exception as e:
        gr.Error(f"Error saving CSV file: {e}")
        return None


def create_tour_api_playwright_tab():
    """'Tour API 직접 조회 (Playwright)' 탭의 UI를 생성합니다."""
    # --- Constants ---
    ITEMS_PER_PAGE = 12
    TEMP_DIR = os.path.join(os.path.dirname(__file__), "Temp")
    os.makedirs(TEMP_DIR, exist_ok=True)
    NO_IMAGE_PLACEHOLDER_PATH = os.path.join(TEMP_DIR, "no_image.svg")
    if not os.path.exists(NO_IMAGE_PLACEHOLDER_PATH):
        svg_content = '''<svg width="100" height="100" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)">
          <rect width="100%" height="100%" fill="#cccccc"/>
          <text x="50%" y="50%" font-family="Arial" font-size="12" fill="#333333" text-anchor="middle" alignment-baseline="middle">No Image</text>
        </svg>'''
        with open(NO_IMAGE_PLACEHOLDER_PATH, "w", encoding="utf-8") as f:
            f.write(svg_content)

    with gr.Blocks(css="""    
        #pagination {justify-content: center; align-items: center;} 
        #pagination .gr-box {max-width: 150px;} 
        #pagination .gr-box.label {max-width: 50px;}
        .tab-content-markdown table {border-collapse: collapse; width: 100%;}
        .tab-content-markdown tr {border-bottom: 1px solid #eee;}
        .tab-content-markdown td {padding: 8px;}
        .tab-content-markdown td:first-child {width: 30%; font-weight: bold; vertical-align: top;}
    """) as demo:
        # --- UI Components & State ---
        search_params = gr.State({})
        current_page = gr.State(1)
        total_pages = gr.State(1)
        current_gallery_data = gr.State([])
        selected_item_info = gr.State({})

        DEFAULT_LARGE_CATEGORIES = ["선택 안함", "자연", "인문(문화/예술/역사)", "레포츠", "쇼핑", "음식", "숙박", "추천코스"]

        gr.Markdown("# TourAPI 4.0 체험 (Playwright + Gradio)")
        gr.Markdown("필터를 선택하고 관광 정보를 검색해보세요.")

        with gr.Row():
            with gr.Column(scale=1):
                with gr.Tabs():
                    with gr.TabItem("지역별 관광정보"):
                        language_dropdown = gr.Dropdown(label="언어", choices=list(scraper.LANGUAGE_MAP.keys()), value="한국어", interactive=True)
                        province_dropdown = gr.Dropdown(label="광역시/도", choices=["전국", "서울", "인천", "대전", "대구", "광주", "부산", "울산", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "경상북도", "경상남도", "전북특별자치도", "전라남도", "제주특별자치도"], value="전국", interactive=True)
                        sigungu_dropdown = gr.Dropdown(label="시/군/구", choices=[], interactive=True)
                        tourism_type_dropdown = gr.Dropdown(label="관광타입", choices=["선택 안함", "관광지", "문화시설", "축제공연행사", "여행코스", "레포츠", "숙박", "쇼핑", "음식점"], value="선택 안함", interactive=True)
                        large_category_dropdown = gr.Dropdown(label="서비스 분류 (대분류)", choices=DEFAULT_LARGE_CATEGORIES, value="선택 안함", interactive=True)
                        medium_category_dropdown = gr.Dropdown(label="서비스 분류 (중분류)", choices=[], interactive=True)
                        small_category_dropdown = gr.Dropdown(label="서비스 분류 (소분류)", choices=[], interactive=True)
                        search_button = gr.Button("검색", variant="primary")

                    with gr.TabItem("내주변 관광정보") as location_tab:
                        loc_language_dropdown = gr.Dropdown(label="언어", choices=list(scraper.LANGUAGE_MAP.keys()), value="한국어", interactive=True)
                        loc_tourism_type_dropdown = gr.Dropdown(label="관광타입", choices=["선택 안함", "관광지", "문화시설", "축제공연행사", "여행코스", "레포츠", "숙박", "쇼핑", "음식점"], value="선택 안함", interactive=True)
                        with gr.Row():
                            map_y_input = gr.Textbox(label="mapY (위도)", value="")
                            map_x_input = gr.Textbox(label="mapX (경도)", value="")
                        with gr.Row():
                            radius_input = gr.Textbox(label="거리 (m)", value="2000")
                            loc_show_map_button = gr.Button("지도보기")
                        loc_search_button = gr.Button("검색", variant="primary")
                        with gr.Group(visible=False) as loc_map_group:
                            loc_map_html = gr.HTML(label="지도")
                            loc_close_map_button = gr.Button("지도 닫기")

                export_csv_button = gr.Button("결과 전체 CSV 저장")
            
            with gr.Column(scale=3):
                status_output = gr.Textbox(label="상태", interactive=False)
                csv_output_file = gr.File(label="CSV 다운로드", interactive=False)
                results_output = gr.Gallery(label="검색 결과", show_label=False, elem_id="gallery", columns=4, height="auto", object_fit="contain", preview=True)
                
                with gr.Row(elem_id="pagination", variant="panel"):
                    first_page_button = gr.Button("<< 맨 처음")
                    prev_page_button = gr.Button("< 이전")
                    page_number_input = gr.Number(label="", value=1, interactive=True, precision=0, minimum=1)
                    total_pages_output = gr.Textbox(label="/", value="/ 1", interactive=False, max_lines=1)
                    next_page_button = gr.Button("다음 >")
                    last_page_button = gr.Button("맨 끝 >>")

                with gr.Accordion("API 요청/응답", visible=False) as api_accordion:
                    request_url_output = gr.Textbox(label="요청 URL", interactive=False)
                    response_xml_output = gr.Code(label="응답 XML", interactive=False)

                with gr.Column(visible=False, elem_id="detail_view") as detail_view_column:
                    detail_title = gr.Markdown("### 제목")
                    with gr.Tabs(elem_id="detail_tabs") as detail_tabs:
                        with gr.TabItem("공통정보", id="공통정보"):
                            detail_image = gr.Image(label="대표 이미지", interactive=False, height=300)
                            detail_info_table = gr.Markdown(elem_id="detail-info-table", elem_classes="tab-content-markdown")
                            detail_overview = gr.Textbox(label="개요", interactive=False, lines=6)
                            show_map_button = gr.Button("지도보기", variant="secondary")
                            with gr.Group(visible=False) as map_group:
                                map_html = gr.HTML(elem_id="map-iframe", label="지도")
                                close_map_button = gr.Button("지도 닫기")
                        with gr.TabItem("소개정보", id="소개정보"):
                            intro_info_markdown = gr.Markdown("소개정보 탭을 선택하여 정보를 확인하세요.", elem_classes="tab-content-markdown")
                        with gr.TabItem("반복정보", id="반복정보"):
                            repeat_info_markdown = gr.Markdown("반복정보 탭을 선택하여 정보를 확인하세요.", elem_classes="tab-content-markdown")
                        with gr.TabItem("추가이미지", id="추가이미지"):
                            additional_images_gallery = gr.Gallery(label="추가 이미지", columns=5, height="auto", object_fit="contain")
        
        # --- Event Handler & Parsing Functions ---

        async def update_sigungu_dropdown(province):
            if not province or province == "전국": return gr.update(choices=[], value=None)
            try:
                sigungu_options = await scraper.get_sigungu_options(province)
                if "전체" not in sigungu_options: sigungu_options.insert(0, "전체")
                return gr.update(choices=sigungu_options, value="전체")
            except Exception: return gr.update(choices=[], value=None)

        async def update_large_category_dropdown(tourism_type):
            if not tourism_type or tourism_type == "선택 안함":
                return gr.update(choices=DEFAULT_LARGE_CATEGORIES, value="선택 안함")
            
            options = await scraper.get_large_category_options(tourism_type)
            return gr.update(choices=["선택 안함"] + options, value="선택 안함")

        async def update_medium_category_dropdown(tourism_type, large_category):
            if not large_category or large_category == "선택 안함": return gr.update(choices=[], value=None)
            options = await scraper.get_medium_category_options(tourism_type, large_category)
            return gr.update(choices=["선택 안함"] + options, value="선택 안함")

        async def update_small_category_dropdown(tourism_type, large_category, medium_category):
            if not medium_category or medium_category == "선택 안함": return gr.update(choices=[], value=None)
            options = await scraper.get_small_category_options(tourism_type, large_category, medium_category)
            return gr.update(choices=["선택 안함"] + options, value="선택 안함")

        async def process_search(params, page_num, total_pages=0):
            page_num = int(page_num)
            
            yield [
                f"{page_num} 페이지를 검색합니다...", # status_output
                [], # results_output
                gr.update(), # api_accordion
                gr.update(), # request_url_output
                gr.update(), # response_xml_output
                gr.update(), # search_params
                gr.update(), # current_page
                gr.update(), # total_pages
                gr.update(), # page_number_input
                gr.update(), # total_pages_output
                gr.update(), # current_gallery_data
                gr.update(visible=False), # detail_view_column
                None, # csv_output_file
            ]

            try:
                search_args = params.copy()
                if search_args.get("sigungu") == "전체": search_args["sigungu"] = None
                if search_args.get("tourism_type") == "선택 안함": search_args["tourism_type"] = None
                if search_args.get("cat1") == "선택 안함": search_args["cat1"] = None
                if search_args.get("cat2") == "선택 안함": search_args["cat2"] = None
                if search_args.get("cat3") == "선택 안함": search_args["cat3"] = None

                results, req_url, xml_res, total_count = await scraper.get_search_results(**search_args, pageNo=page_num, temp_dir=TEMP_DIR, totalPages=total_pages)
                
                if page_num == 1:
                    total_pages_val = math.ceil(total_count / ITEMS_PER_PAGE) if total_count > 0 else 1
                else:
                    total_pages_val = total_pages

                gallery_data = [(item['image'] if item.get('image') else NO_IMAGE_PLACEHOLDER_PATH, item['title']) for item in results]
                
                status_message = f"총 {total_count}개 검색 완료 (페이지 {page_num}/{total_pages_val})"
                if not results: 
                    status_message = "검색 결과가 없습니다."

                yield [
                    status_message, # status_output
                    gallery_data, # results_output
                    gr.update(visible=True), # api_accordion
                    req_url, # request_url_output
                    xml_res, # response_xml_output
                    params, # search_params
                    page_num, # current_page
                    total_pages_val, # total_pages
                    page_num, # page_number_input
                    f"/ {total_pages_val}", # total_pages_output
                    results, # current_gallery_data
                    gr.update(visible=False), # detail_view_column
                    None # csv_output_file
                ]
            except Exception as e:
                yield [
                    f"검색 중 오류 발생: {e}", # status_output
                    [], # results_output
                    gr.update(), # api_accordion
                    gr.update(), # request_url_output
                    gr.update(), # response_xml_output
                    gr.update(), # search_params
                    gr.update(), # current_page
                    gr.update(), # total_pages
                    gr.update(), # page_number_input
                    gr.update(), # total_pages_output
                    gr.update(), # current_gallery_data
                    gr.update(visible=False), # detail_view_column
                    None, # csv_output_file
                ]

        async def initial_search(lang, prov, sig, tour, c1, c2, c3):
            params = {"search_type": "area", "language": lang, "province": prov, "sigungu": sig, "tourism_type": tour, "cat1": c1, "cat2": c2, "cat3": c3}
            async for update in process_search(params, 1, 0): yield update
            
        async def initial_loc_search(lang, tour, map_x, map_y, radius):
            params = {"search_type": "location", "language": lang, "tourism_type": tour, "map_x": map_x, "map_y": map_y, "radius": radius}
            async for update in process_search(params, 1, 0): yield update

        async def change_page(page_num, stored_params):
            async for update in process_search(stored_params, int(page_num)): yield update

        def parse_xml_to_html_table(xml_string):
            try:
                root = ET.fromstring(xml_string)
                items = root.findall('.//body/items/item')
                if not items:
                    return "<p>정보가 없습니다.</p>"

                html = "<table>"
                
                # '반복정보'나 '소개정보'와 같이 여러 정보 항목이 있는 경우
                if len(items) > 1 and any(item.find('infoname') is not None for item in items):
                    for item in items:
                        infoname = item.findtext('infoname', '')
                        infotext = item.findtext('infotext', '').replace('\n', '<br>')
                        html += f"<tr><td>{infoname}</td><td>{infotext}</td></tr>"
                # '공통정보'와 같이 단일 항목인 경우
                else:
                    item = items[0]
                    for child in item:
                        tag_name = child.tag
                        if tag_name in ['contentid', 'contenttypeid', 'createdtime', 'modifiedtime', 'firstimage', 'firstimage2', 'cpyrhtDivCd', 'areacode', 'sigungucode', 'cat1', 'cat2', 'cat3', 'mapx', 'mapy', 'mlevel', 'overview', 'title']:
                            continue
                        tag_text = child.text.replace('\n', '<br>') if child.text else ''
                        html += f"<tr><td>{tag_name}</td><td>{tag_text}</td></tr>"

                html += "</table>"
                return html
            except Exception as e:
                return f"<p>XML 파싱 중 오류 발생: {e}</p>"

        def parse_common_info_xml(xml_string):
            try:
                root = ET.fromstring(xml_string)
                item = root.find('.//body/items/item')
                if item is None: return {}
                return {child.tag: child.text for child in item if child.text is not None}
            except: return {}

        def parse_images_xml(xml_string):
            try:
                root = ET.fromstring(xml_string)
                urls = [item.find('originimgurl').text for item in root.findall('.//body/items/item') if item.find('originimgurl') is not None]
                return urls # URL 리스트를 직접 반환
            except Exception:
                return []

        async def show_initial_details(evt: gr.SelectData, s_params, g_data, c_page):
            if not g_data or evt.index is None:
                yield {detail_view_column: gr.update(visible=False)}
                return
            
            selected_item = g_data[evt.index]
            title = selected_item['title']
            
            info_for_tabs = s_params.copy()
            if info_for_tabs.get("province") == "전국": info_for_tabs["province"] = None
            if info_for_tabs.get("tourism_type") == "선택 안함": info_for_tabs["tourism_type"] = None
            if info_for_tabs.get("sigungu") == "전체": info_for_tabs["sigungu"] = None
            if info_for_tabs.get("cat1") == "선택 안함": info_for_tabs["cat1"] = None
            if info_for_tabs.get("cat2") == "선택 안함": info_for_tabs["cat2"] = None
            if info_for_tabs.get("cat3") == "선택 안함": info_for_tabs["cat3"] = None
            info_for_tabs.update({"contentid": selected_item.get("contentid"), "pageNo": c_page, "coords": {"mapx": selected_item.get("mapx"), "mapy": selected_item.get("mapy")}})

            yield {status_output: f"'{title}' 상세 정보 로딩 중...", detail_view_column: gr.update(visible=False)}
            
            try:
                args = {k: v for k, v in info_for_tabs.items() if k not in ['coords']}
                args["tab_name"] = "공통정보"
                
                xml_string = await scraper.get_item_detail_xml(args)
                
                if "<error>" in xml_string: raise ValueError(xml_string)
                
                common_data = parse_common_info_xml(xml_string)
                
                update_dict = {
                    status_output: f"'{title}' 상세 정보 로드 완료.",
                    detail_view_column: gr.update(visible=True),
                    detail_title: gr.update(value=f"### {common_data.get('title', '')}"),
                    detail_image: gr.update(value=common_data.get('firstimage')),
                    detail_overview: gr.update(value=common_data.get('overview')),
                    detail_info_table: gr.update(value=parse_xml_to_html_table(xml_string)),
                    selected_item_info: info_for_tabs,
                    map_group: gr.update(visible=False),
                    intro_info_markdown: "소개정보 탭을 선택하여 정보를 확인하세요.",
                    repeat_info_markdown: "반복정보 탭을 선택하여 정보를 확인하세요.",
                    additional_images_gallery: []
                }
                yield update_dict
            except Exception as e:
                yield {status_output: f"상세 정보 로딩 중 오류: {e}", detail_view_column: gr.update(visible=True), detail_title: "오류", detail_overview: str(e)}

        async def update_tab_content(evt: gr.SelectData, item_info):
            if not item_info or not evt:
                yield {intro_info_markdown: gr.update(), repeat_info_markdown: gr.update(), additional_images_gallery: gr.update()}
                return
            
            tab_name = evt.value
            yield {
                intro_info_markdown: "로딩 중..." if tab_name == "소개정보" else gr.update(),
                repeat_info_markdown: "로딩 중..." if tab_name == "반복정보" else gr.update(),
                additional_images_gallery: [] if tab_name == "추가이미지" else gr.update()
            }
            
            args = {k: v for k, v in item_info.items() if k not in ['coords']}
            args["tab_name"] = tab_name
            
            xml_string = await scraper.get_item_detail_xml(args)
            
            if "<error>" in xml_string:
                yield {
                    intro_info_markdown: xml_string if tab_name == "소개정보" else gr.update(),
                    repeat_info_markdown: xml_string if tab_name == "반복정보" else gr.update(),
                    additional_images_gallery: []
                }
                return

            if tab_name == "소개정보": yield {intro_info_markdown: parse_xml_to_html_table(xml_string)}
            elif tab_name == "반복정보": yield {repeat_info_markdown: parse_xml_to_html_table(xml_string)}
            elif tab_name == "추가이미지": yield {additional_images_gallery: parse_images_xml(xml_string)}

        def show_map(item_info):
            coords = item_info.get('coords', {})
            mapx, mapy = coords.get('mapx'), coords.get('mapy')
            if not mapx or not mapy: return gr.update(value="<p>좌표 정보가 없어 지도를 표시할 수 없습니다.</p>")
            map_url = f"[https://maps.google.com/maps?q=](https://maps.google.com/maps?q=){mapy},{mapx}&hl=ko&z=15&output=embed"
            return gr.update(value=f'<iframe src="{map_url}" style="width: 100%; height: 400px; border: none;"></iframe>')

        def show_loc_map(mapx, mapy):
            if not mapx or not mapy: return gr.update(value="<p>좌표 정보가 없어 지도를 표시할 수 없습니다.</p>")
            map_url = f"[https://maps.google.com/maps?q=](https://maps.google.com/maps?q=){mapy},{mapx}&hl=ko&z=15&output=embed"
            return gr.update(value=f'<iframe src="{map_url}" style="width: 100%; height: 400px; border: none;"></iframe>')

        # --- Attach Event Handlers ---
        search_inputs = [language_dropdown, province_dropdown, sigungu_dropdown, tourism_type_dropdown, 
                         large_category_dropdown, medium_category_dropdown, small_category_dropdown]
        search_outputs = [status_output, results_output, api_accordion, request_url_output, response_xml_output, 
                          search_params, current_page, total_pages, page_number_input, total_pages_output, current_gallery_data, detail_view_column, csv_output_file]
        
        loc_search_inputs = [loc_language_dropdown, loc_tourism_type_dropdown, map_x_input, map_y_input, radius_input]

        detail_outputs = [status_output, detail_view_column, detail_title, detail_image, detail_overview, 
                          detail_info_table, selected_item_info, map_group, 
                          intro_info_markdown, repeat_info_markdown, additional_images_gallery]

        province_dropdown.change(update_sigungu_dropdown, inputs=province_dropdown, outputs=sigungu_dropdown)
        tourism_type_dropdown.change(update_large_category_dropdown, inputs=tourism_type_dropdown, outputs=large_category_dropdown).then(lambda: (gr.update(choices=[], value=None), gr.update(choices=[], value=None)), outputs=[medium_category_dropdown, small_category_dropdown])
        large_category_dropdown.change(update_medium_category_dropdown, inputs=[tourism_type_dropdown, large_category_dropdown], outputs=medium_category_dropdown).then(lambda: gr.update(choices=[], value=None), outputs=[small_category_dropdown])
        medium_category_dropdown.change(update_small_category_dropdown, inputs=[tourism_type_dropdown, large_category_dropdown, medium_category_dropdown], outputs=small_category_dropdown)

        search_button.click(fn=initial_search, inputs=search_inputs, outputs=search_outputs, queue=True)
        loc_search_button.click(fn=initial_loc_search, inputs=loc_search_inputs, outputs=search_outputs, queue=True)
        export_csv_button.click(fn=export_details_to_csv, inputs=[search_params], outputs=[csv_output_file], queue=True)

        location_tab.select(fn=None, js=get_location_js, outputs=[map_y_input, map_x_input])

        loc_show_map_button.click(fn=show_loc_map, inputs=[map_x_input, map_y_input], outputs=[loc_map_html]).then(lambda: gr.update(visible=True), outputs=[loc_map_group])
        loc_close_map_button.click(lambda: gr.update(visible=False), outputs=[loc_map_group])

        async def change_page(page_num, stored_params, total_pages=0):
            async for update in process_search(stored_params, int(page_num), total_pages): yield update

        async def go_to_first_page(p):
            async for update in change_page(1, p, 0): yield update
        async def go_to_prev_page(current_page_num, tp, p):
            async for update in change_page(max(1, int(current_page_num) - 1), p, tp): yield update
        async def go_to_next_page(current_page_num, tp, p):
            async for update in change_page(min(int(current_page_num) + 1, tp), p, tp): yield update
        async def go_to_last_page(tp, p):
            async for update in change_page(tp, p, tp): yield update
        async def go_to_specific_page(pn, tp, p):
            async for update in change_page(pn, p, tp): yield update

        first_page_button.click(fn=go_to_first_page, inputs=[search_params], outputs=search_outputs, queue=True)
        prev_page_button.click(fn=go_to_prev_page, inputs=[page_number_input, total_pages, search_params], outputs=search_outputs, queue=True)
        next_page_button.click(fn=go_to_next_page, inputs=[page_number_input, total_pages, search_params], outputs=search_outputs, queue=True)
        last_page_button.click(fn=go_to_last_page, inputs=[total_pages, search_params], outputs=search_outputs, queue=True)
        page_number_input.submit(fn=go_to_specific_page, inputs=[page_number_input, total_pages, search_params], outputs=search_outputs, queue=True)

        results_output.select(fn=show_initial_details, inputs=[search_params, current_gallery_data, current_page], outputs=detail_outputs, queue=True)

        detail_tabs.select(fn=update_tab_content, inputs=[selected_item_info], outputs=[intro_info_markdown, repeat_info_markdown, additional_images_gallery], queue=True)

        show_map_button.click(fn=show_map, inputs=[selected_item_info], outputs=[map_html]).then(lambda: gr.update(visible=True), outputs=[map_group])
        close_map_button.click(lambda: gr.update(visible=False), outputs=[map_group])

    return demo

def create_naver_search_tab():
    """'네이버 검색 (임시)' 탭의 UI를 생성합니다."""
    with gr.Blocks() as tab:
        gr.Markdown("### 네이버 블로그 후기 검색 및 요약")
        
        # --- 상태 변수 ---
        search_results_state = gr.State([])

        # --- UI 컴포넌트 ---
        with gr.Row():
            keyword_input = gr.Textbox(
                label="검색할 행사 키워드를 입력하세요",
                placeholder="예: 2025 한강 불빛 공연",
                lines=1,
                scale=3
            )
            search_button = gr.Button("검색 실행", variant="primary", scale=1)
            summarize_button = gr.Button("결과 요약하기", scale=1)

        gr.Markdown("--- ")
        summary_output = gr.Markdown(label="방문객 경험 중심 요약 (GPT-4.1-mini)")
        image_gallery = gr.Gallery(label="블로그 이미지 모아보기", columns=6, height="auto")
        
        gr.Markdown("---")
        gr.Markdown("### 💬 후기 기반 챗봇")
        gr.Markdown("블로그 후기 내용을 바탕으로 궁금한 점을 질문해보세요. (예: 주차 정보, 유모차 끌기 편한가요?, 비 오는 날 가도 괜찮나요?)")
        
        with gr.Row():
            question_input = gr.Textbox(label="질문 입력", placeholder="질문을 입력하세요...", scale=4)
            ask_button = gr.Button("질문하기", scale=1)
        
        answer_output = gr.Markdown(label="챗봇 답변")

        gr.Markdown("---")
        with gr.Row():
            raw_json_output = gr.Textbox(
                label="Raw JSON 결과", 
                lines=20, 
                interactive=False
            )
            formatted_output = gr.Markdown()
            
        # --- 이벤트 핸들러 ---
        search_button.click(
            fn=search_naver_reviews_and_scrape,
            inputs=[keyword_input],
            outputs=[raw_json_output, formatted_output, search_results_state, image_gallery]
        )

        summarize_button.click(
            fn=summarize_blog_contents_stream,
            inputs=[search_results_state],
            outputs=[summary_output]
        )

        ask_button.click(
            fn=answer_question_from_reviews_stream,
            inputs=[question_input, search_results_state],
            outputs=[answer_output]
        )
    return tab

# --- Gradio TabbedInterface를 사용하여 전체 UI 구성 ---
demo = gr.TabbedInterface(
    [create_location_search_tab(), create_area_search_tab(), create_seoul_search_ui(), create_naver_search_tab(), create_tour_api_playwright_tab()],
    tab_names=["내 위치로 검색", "지역/카테고리별 검색 (기존 TourAPI)", "서울시 관광지 검색 (신규)", "네이버 검색 (임시)", "Tour API 직접 조회 (Playwright)"],
    title="TourLens 관광 정보 앱"
)

# --- 애플리케이션 실행 ---
if __name__ == "__main__":
    # .env 파일 및 필수 키 확인 (기존 TourAPI 키 확인 부분은 주석 처리하거나 삭제 가능)
    if not os.getenv("TOUR_API_KEY"):
        print("TourAPI 키가 설정되지 않았습니다. .env 파일에 TOUR_API_KEY를 추가해주세요.")
        exit()
    if not os.getenv("NAVER_CLIENT_ID") or not os.getenv("NAVER_CLIENT_SECRET"):
        print("네이버 블로그 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        exit()
    if not os.getenv("NAVER_TREND_CLIENT_ID") or not os.getenv("NAVER_TREND_CLIENT_SECRET"):
        print("네이버 트렌드 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        exit()

    demo.launch(debug=True)