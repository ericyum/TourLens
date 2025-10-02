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
from modules.trend_analyzer import (
    generate_trends_from_area_search,
    generate_trends_from_location_search,
    analyze_single_item,
    analyze_trends_for_titles
)
# 서울 관광 API 모듈
from modules.seoul_search.seoul_api import get_all_seoul_data
# 네이버 검색 모듈
from modules.naver_search import search_naver_reviews_and_scrape, summarize_blog_contents_stream, answer_question_from_reviews_stream


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
        gr.update(interactive=page_to_go > 1),
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
            cleaned_value = str(value).replace('\r\n', ' ').strip()
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
    [create_location_search_tab(), create_area_search_tab(), create_seoul_search_ui(), create_naver_search_tab()],
    tab_names=["내 위치로 검색", "지역/카테고리별 검색 (기존 TourAPI)", "서울시 관광지 검색 (신규)", "네이버 검색 (임시)"],
    title="TourLens 관광 정보 앱"
)

# --- 애플리케이션 실행 ---
if __name__ == "__main__":
    # .env 파일 및 필수 키 확인 (기존 TourAPI 키 확인 부분은 주석 처리하거나 삭제 가능)
    # if not os.getenv("TOUR_API_KTY"):
    #     print("TourAPI 키가 설정되지 않았습니다. .env 파일에 TOUR_API_KTY를 추가해주세요.")
    #     exit()
    if not os.getenv("NAVER_CLIENT_ID") or not os.getenv("NAVER_CLIENT_SECRET"):
        print("네이버 블로그 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        exit()
    if not os.getenv("NAVER_TREND_CLIENT_ID") or not os.getenv("NAVER_TREND_CLIENT_SECRET"):
        print("네이버 트렌드 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        exit()

    demo.launch(debug=True)