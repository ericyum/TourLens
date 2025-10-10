import gradio as gr
import os
import datetime
import math
import re
import xml.etree.ElementTree as ET

from . import scraper
from .total_search.search import get_total_search_results, get_total_search_item_detail_xml
from .date_search.search import get_date_search_results, get_date_search_item_detail_xml
from .export import export_details_to_csv
from ..tour_api_search.location_search.location import get_location_js

def create_tour_api_playwright_tab():
    """'Tour API 직접 조회 (Playwright)' 탭의 UI를 생성합니다."""
    # --- Constants ---
    ITEMS_PER_PAGE = 12
    TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Temp")
    os.makedirs(TEMP_DIR, exist_ok=True)
    NO_IMAGE_PLACEHOLDER_PATH = os.path.join(TEMP_DIR, "no_image.svg")
    if not os.path.exists(NO_IMAGE_PLACEHOLDER_PATH):
        svg_content = '''<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
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
    """ ) as demo:
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
                with gr.Tabs() as api_tabs:
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

                    with gr.TabItem("통합 검색"):
                        total_language_dropdown = gr.Dropdown(label="언어", choices=list(scraper.LANGUAGE_MAP.keys()), value="한국어", interactive=True)
                        total_province_dropdown = gr.Dropdown(label="광역시/도", choices=["전국", "서울", "인천", "대전", "대구", "광주", "부산", "울산", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "경상북도", "경상남도", "전북특별자치도", "전라남도", "제주특별자치도"], value="전국", interactive=True)
                        total_sigungu_dropdown = gr.Dropdown(label="시/군/구", choices=[], interactive=True)
                        total_large_category_dropdown = gr.Dropdown(label="서비스 분류 (대분류)", choices=DEFAULT_LARGE_CATEGORIES, value="선택 안함", interactive=True)
                        total_medium_category_dropdown = gr.Dropdown(label="서비스 분류 (중분류)", choices=[], interactive=True)
                        total_small_category_dropdown = gr.Dropdown(label="서비스 분류 (소분류)", choices=[], interactive=True)
                        total_keyword_input = gr.Textbox(label="검색어", placeholder="검색어를 입력하세요...", interactive=True)
                        total_search_button = gr.Button("검색", variant="primary")

                    with gr.TabItem("행사 검색"):
                        today = datetime.date.today()
                        start_default = today.strftime("%Y-%m-%d")
                        end_default = (today + datetime.timedelta(days=30)).strftime("%Y-%m-%d")

                        date_language_dropdown = gr.Dropdown(label="언어", choices=list(scraper.LANGUAGE_MAP.keys()), value="한국어", interactive=True)
                        date_province_dropdown = gr.Dropdown(label="광역시/도", choices=["전국", "서울", "인천", "대전", "대구", "광주", "부산", "울산", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "경상북도", "경상남도", "전북특별자치도", "전라남도", "제주특별자치도"], value="전국", interactive=True)
                        date_sigungu_dropdown = gr.Dropdown(label="시/군/구", choices=[], interactive=True)
                        start_date_input = gr.Textbox(label="시작일", value=start_default, placeholder="YYYY-MM-DD", interactive=True)
                        end_date_input = gr.Textbox(label="종료일", value=end_default, placeholder="YYYY-MM-DD", interactive=True)
                        date_search_button = gr.Button("검색", variant="primary")

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
                        with gr.TabItem("반복정보", id="반복정보", visible=True) as repeat_info_tab:
                            repeat_info_markdown = gr.Markdown("반복정보 탭을 선택하여 정보를 확인하세요.", elem_classes="tab-content-markdown")
                        with gr.TabItem("코스 정보", id="코스 정보", visible=False) as course_info_tab:
                            course_info_markdown = gr.Markdown("코스 정보 탭을 선택하여 정보를 확인하세요.", elem_classes="tab-content-markdown")
                        with gr.TabItem("객실 정보", id="객실 정보", visible=False) as room_info_tab:
                            room_info_markdown = gr.Markdown("객실 정보 탭을 선택하여 정보를 확인하세요.", elem_classes="tab-content-markdown")
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
                search_type = search_args.get("search_type", "area")

                if search_type != "total":
                    if search_args.get("sigungu") == "전체": search_args["sigungu"] = None
                    if search_args.get("tourism_type") == "선택 안함": search_args["tourism_type"] = None
                    if search_args.get("cat1") == "선택 안함": search_args["cat1"] = None
                    if search_args.get("cat2") == "선택 안함": search_args["cat2"] = None
                    if search_args.get("cat3") == "선택 안함": search_args["cat3"] = None

                if search_type == "total":
                    results, req_url, xml_res, total_count = await get_total_search_results(**search_args, pageNo=page_num, temp_dir=TEMP_DIR, totalPages=total_pages)
                elif search_type == "date":
                    results, req_url, xml_res, total_count = await get_date_search_results(**search_args, pageNo=page_num, temp_dir=TEMP_DIR, totalPages=total_pages)
                else:
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

        async def initial_total_search(lang, prov, sig, c1, c2, c3, keyword):
            params = {"search_type": "total", "language": lang, "province": prov, "sigungu": sig, "tourism_type": "선택 안함", "cat1": c1, "cat2": c2, "cat3": c3, "keyword": keyword}
            async for update in process_search(params, 1, 0): yield update

        async def initial_date_search(lang, prov, sig, start_date, end_date):
            params = {"search_type": "date", "language": lang, "province": prov, "sigungu": sig, "start_date": start_date, "end_date": end_date}
            async for update in process_search(params, 1, 0): yield update

        async def change_page(page_num, stored_params):
            async for update in process_search(stored_params, int(page_num)): yield update

        def parse_xml_to_html_table(xml_string, content_type_id, tab_name="공통정보"):
            try:
                root = ET.fromstring(xml_string)
                items = root.findall('.//body/items/item')
                if not items:
                    return "<p>정보가 없습니다.</p>"

                html = "<table>"
                
                if tab_name == "코스 정보":
                    headers = {'subname': '코스명', 'subdetailoverview': '개요'}
                    html += "<thead><tr>"
                    for header_ko in headers.values(): html += f"<th>{header_ko}</th>"
                    html += "</tr></thead><tbody>"
                    for item in items:
                        html += "<tr>"
                        for key in headers.keys():
                            text = item.findtext(key, '').replace('\n', '<br>')
                            html += f"<td>{text}</td>"
                        html += "</tr>"
                    html += "</tbody>"
                elif tab_name == "객실 정보":
                    headers = {'roomtitle': '객실명', 'roomsize1': '크기(평)', 'roombasecount': '기본인원', 'roommaxcount': '최대인원', 'roomoffseasonminfee1': '비수기 주중 최소', 'roompeakseasonminfee1': '성수기 주중 최소'}
                    html += "<thead><tr>"
                    for header_ko in headers.values(): html += f"<th>{header_ko}</th>"
                    html += "</tr></thead><tbody>"
                    for item in items:
                        html += "<tr>"
                        for key in headers.keys():
                            text = item.findtext(key, '').replace('\n', '<br>')
                            html += f"<td>{text}</td>"
                        html += "</tr>"
                    html += "</tbody>"
                elif tab_name == "반복정보":
                    for item in items:
                        infoname = item.findtext('infoname', '')
                        infotext = item.findtext('infotext', '').replace('\n', '<br>')
                        html += f"<tr><td>{infoname}</td><td>{infotext}</td></tr>"
                else: # 공통 또는 소개정보
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
                return urls
            except Exception:
                return []

        async def show_initial_details(evt: gr.SelectData, s_params, g_data, c_page):
            if not g_data or evt.index is None:
                yield {detail_view_column: gr.update(visible=False)}
                return
            
            selected_item = g_data[evt.index]
            title = selected_item['title']
            # Defensive coding: Ensure content_type_id is a string and stripped of whitespace
            content_type_id = str(selected_item.get('contenttypeid') or '').strip()
            
            info_for_tabs = s_params.copy()
            if info_for_tabs.get("province") == "전국": info_for_tabs["province"] = None
            if info_for_tabs.get("tourism_type") == "선택 안함": info_for_tabs["tourism_type"] = None
            if info_for_tabs.get("sigungu") == "전체": info_for_tabs["sigungu"] = None
            if info_for_tabs.get("cat1") == "선택 안함": info_for_tabs["cat1"] = None
            if info_for_tabs.get("cat2") == "선택 안함": info_for_tabs["cat2"] = None
            if info_for_tabs.get("cat3") == "선택 안함": info_for_tabs["cat3"] = None
            info_for_tabs.update({"contentid": selected_item.get("contentid"), "contenttypeid": content_type_id, "pageNo": c_page, "coords": {"mapx": selected_item.get("mapx"), "mapy": selected_item.get("mapy")}})

            yield {status_output: f"'{title}' 상세 정보 로딩 중...", detail_view_column: gr.update(visible=False)}
            
            try:
                args = {k: v for k, v in info_for_tabs.items() if k not in ['coords']}
                args["tab_name"] = "공통정보"
                
                xml_string = ""
                search_type = s_params.get("search_type")
                if search_type == "total":
                    xml_string = await get_total_search_item_detail_xml(args)
                elif search_type == "date":
                    xml_string = await get_date_search_item_detail_xml(args)
                else:
                    xml_string = await scraper.get_item_detail_xml(args)
                
                if "<error>" in xml_string: raise ValueError(xml_string)
                
                common_data = parse_common_info_xml(xml_string)
                
                # Explicitly define visibility for each tab type
                is_course = content_type_id == '25'
                is_lodging = content_type_id == '32'
                is_normal_repeat = not is_course and not is_lodging

                update_dict = {
                    status_output: f"'{title}' 상세 정보 로드 완료.",
                    detail_view_column: gr.update(visible=True),
                    detail_title: gr.update(value=f"### {common_data.get('title', '')}"),
                    detail_image: gr.update(value=common_data.get('firstimage')),
                    detail_overview: gr.update(value=common_data.get('overview')),
                    detail_info_table: gr.update(value=parse_xml_to_html_table(xml_string, content_type_id, tab_name="공통정보")),
                    selected_item_info: info_for_tabs,
                    map_group: gr.update(visible=False),
                    intro_info_markdown: "소개정보 탭을 선택하여 정보를 확인하세요.",
                    repeat_info_markdown: "" if not is_normal_repeat else "반복정보 탭을 선택하여 정보를 확인하세요.",
                    course_info_markdown: "" if not is_course else "코스 정보 탭을 선택하여 정보를 확인하세요.",
                    room_info_markdown: "" if not is_lodging else "객실 정보 탭을 선택하여 정보를 확인하세요.",
                    additional_images_gallery: [],
                    # Apply the logic to control tab visibility
                    repeat_info_tab: gr.update(visible=is_normal_repeat),
                    course_info_tab: gr.update(visible=is_course),
                    room_info_tab: gr.update(visible=is_lodging),
                }
                yield update_dict
            except Exception as e:
                yield {status_output: f"상세 정보 로딩 중 오류: {e}", detail_view_column: gr.update(visible=True), detail_title: "오류", detail_overview: str(e)}

        async def update_tab_content(evt: gr.SelectData, item_info):
            if not item_info or not evt:
                # [수정] 모든 마크다운 출력을 포함하도록 수정
                yield {intro_info_markdown: gr.update(), repeat_info_markdown: gr.update(), course_info_markdown: gr.update(), room_info_markdown: gr.update(), additional_images_gallery: gr.update()}
                return
            
            tab_name = evt.value
            content_type_id = item_info.get('contenttypeid')

            # [수정] 모든 마크다운 출력을 포함하도록 수정
            yield {
                intro_info_markdown: "로딩 중..." if tab_name == "소개정보" else gr.update(),
                repeat_info_markdown: "로딩 중..." if tab_name == "반복정보" else gr.update(),
                course_info_markdown: "로딩 중..." if tab_name == "코스 정보" else gr.update(),
                room_info_markdown: "로딩 중..." if tab_name == "객실 정보" else gr.update(),
                additional_images_gallery: [] if tab_name == "추가이미지" else gr.update()
            }
            
            args = {k: v for k, v in item_info.items() if k not in ['coords']}
            args["tab_name"] = tab_name
            
            xml_string = ""
            search_type = item_info.get("search_type")
            if search_type == "total":
                xml_string = await get_total_search_item_detail_xml(args)
            elif search_type == "date":
                xml_string = await get_date_search_item_detail_xml(args)
            else:
                xml_string = await scraper.get_item_detail_xml(args)
            
            if "<error>" in xml_string:
                update_dict = {k: gr.update() for k in [intro_info_markdown, repeat_info_markdown, course_info_markdown, room_info_markdown, additional_images_gallery]}
                if tab_name == "소개정보": update_dict[intro_info_markdown] = xml_string
                elif tab_name == "반복정보": update_dict[repeat_info_markdown] = xml_string
                elif tab_name == "코스 정보": update_dict[course_info_markdown] = xml_string
                elif tab_name == "객실 정보": update_dict[room_info_markdown] = xml_string
                yield update_dict
                return

            html_table = parse_xml_to_html_table(xml_string, content_type_id, tab_name=tab_name)
            images = parse_images_xml(xml_string) if tab_name == "추가이미지" else None

            update_dict = {k: gr.update() for k in [intro_info_markdown, repeat_info_markdown, course_info_markdown, room_info_markdown, additional_images_gallery]}
            if tab_name == "소개정보": update_dict[intro_info_markdown] = html_table
            elif tab_name == "반복정보": update_dict[repeat_info_markdown] = html_table
            elif tab_name == "코스 정보": update_dict[course_info_markdown] = html_table
            elif tab_name == "객실 정보": update_dict[room_info_markdown] = html_table
            elif tab_name == "추가이미지": update_dict[additional_images_gallery] = images
            yield update_dict

        def show_map(item_info):
            coords = item_info.get('coords', {})
            mapx, mapy = coords.get('mapx'), coords.get('mapy')
            if not mapx or not mapy: return gr.update(value="<p>좌표 정보가 없어 지도를 표시할 수 없습니다.</p>")
            map_url = f"https://maps.google.com/maps?q={mapy},{mapx}&hl=ko&z=15&output=embed"
            return gr.update(value=f'<iframe src="{map_url}" style="width: 100%; height: 400px; border: none;"></iframe>')

        def show_loc_map(mapx, mapy):
            if not mapx or not mapy: return gr.update(value="<p>좌표 정보가 없어 지도를 표시할 수 없습니다.</p>")
            map_url = f"https://maps.google.com/maps?q={mapy},{mapx}&hl=ko&z=15&output=embed"
            return gr.update(value=f'<iframe src="{map_url}" style="width: 100%; height: 400px; border: none;"></iframe>')

        # --- Attach Event Handlers ---
        search_inputs = [language_dropdown, province_dropdown, sigungu_dropdown, tourism_type_dropdown, 
                         large_category_dropdown, medium_category_dropdown, small_category_dropdown]
        search_outputs = [status_output, results_output, api_accordion, request_url_output, response_xml_output, 
                          search_params, current_page, total_pages, page_number_input, total_pages_output, current_gallery_data, detail_view_column, csv_output_file]
        
        loc_search_inputs = [loc_language_dropdown, loc_tourism_type_dropdown, map_x_input, map_y_input, radius_input]
        total_search_inputs = [total_language_dropdown, total_province_dropdown, total_sigungu_dropdown, total_large_category_dropdown, total_medium_category_dropdown, total_small_category_dropdown, total_keyword_input]
        date_search_inputs = [date_language_dropdown, date_province_dropdown, date_sigungu_dropdown, start_date_input, end_date_input]

        detail_outputs = [status_output, detail_view_column, detail_title, detail_image, detail_overview, 
                          detail_info_table, selected_item_info, map_group, 
                          intro_info_markdown, repeat_info_markdown, course_info_markdown, room_info_markdown, additional_images_gallery,
                          repeat_info_tab, course_info_tab, room_info_tab]

        api_tabs.change(lambda: gr.update(interactive=True), outputs=[export_csv_button])

        province_dropdown.change(update_sigungu_dropdown, inputs=province_dropdown, outputs=sigungu_dropdown)
        tourism_type_dropdown.change(update_large_category_dropdown, inputs=tourism_type_dropdown, outputs=large_category_dropdown).then(lambda: (gr.update(choices=[], value=None), gr.update(choices=[], value=None)), outputs=[medium_category_dropdown, small_category_dropdown])
        large_category_dropdown.change(update_medium_category_dropdown, inputs=[tourism_type_dropdown, large_category_dropdown], outputs=medium_category_dropdown).then(lambda: gr.update(choices=[], value=None), outputs=[small_category_dropdown])
        medium_category_dropdown.change(update_small_category_dropdown, inputs=[tourism_type_dropdown, large_category_dropdown, medium_category_dropdown], outputs=small_category_dropdown)

        total_province_dropdown.change(update_sigungu_dropdown, inputs=total_province_dropdown, outputs=total_sigungu_dropdown)
        total_large_category_dropdown.change(update_medium_category_dropdown, inputs=[gr.State("선택 안함"), total_large_category_dropdown], outputs=total_medium_category_dropdown).then(lambda: gr.update(choices=[], value=None), outputs=[total_small_category_dropdown])
        total_medium_category_dropdown.change(update_small_category_dropdown, inputs=[gr.State("선택 안함"), total_large_category_dropdown, total_medium_category_dropdown], outputs=total_small_category_dropdown)

        date_province_dropdown.change(update_sigungu_dropdown, inputs=date_province_dropdown, outputs=date_sigungu_dropdown)


        search_button.click(fn=initial_search, inputs=search_inputs, outputs=search_outputs, queue=True)
        loc_search_button.click(fn=initial_loc_search, inputs=loc_search_inputs, outputs=search_outputs, queue=True)
        total_search_button.click(fn=initial_total_search, inputs=total_search_inputs, outputs=search_outputs, queue=True)
        date_search_button.click(fn=initial_date_search, inputs=date_search_inputs, outputs=search_outputs, queue=True)
        
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

        detail_tabs.select(fn=update_tab_content, inputs=[selected_item_info], outputs=[intro_info_markdown, repeat_info_markdown, course_info_markdown, room_info_markdown, additional_images_gallery], queue=True)

        show_map_button.click(fn=show_map, inputs=[selected_item_info], outputs=[map_html]).then(lambda: gr.update(visible=True), outputs=[map_group])
        close_map_button.click(lambda: gr.update(visible=False), outputs=[map_group])

    return demo
