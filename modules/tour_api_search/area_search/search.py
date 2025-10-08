import gradio as gr
import math
from utils import common_params, session, BASE_URL, get_api_items
from modules.tour_api_search.area_search.controls import AREA_CODES, CONTENT_TYPE_CODES

ROWS_PER_PAGE = 10
PAGE_WINDOW_SIZE = 5

def update_page_view(area_name, sigungu_name, category_name, page_to_go):
    """페이지네이션의 핵심 로직: 모든 필터를 적용하여 페이지 데이터 로드 및 UI 업데이트"""
    try:
        page_to_go = int(page_to_go)
        area_code = AREA_CODES.get(area_name)
        content_type_id = CONTENT_TYPE_CODES.get(category_name)

        params = {**common_params, "areaCode": area_code, "numOfRows": ROWS_PER_PAGE, "pageNo": page_to_go}
        if sigungu_name and sigungu_name != "전체":
            sigungu_response = session.get(f"{BASE_URL}areaCode2", params={**common_params, "areaCode": area_code, "numOfRows": "100"})
            sigungu_response.raise_for_status()
            
            sigungu_items = get_api_items(sigungu_response.json())
            
            sigungu_code = next((item['code'] for item in sigungu_items if isinstance(item, dict) and item.get('name') == sigungu_name), None)
            if sigungu_code: params["sigunguCode"] = sigungu_code
        if content_type_id:
            params["contentTypeId"] = content_type_id

        response = session.get(f"{BASE_URL}areaBasedList2", params=params)
        response.raise_for_status()
        data = response.json()
        
        items = get_api_items(data)
        
        body = data.get('response', {}).get('body', {})
        if not isinstance(body, dict): body = {}
        
        places_info = {
            item['title']: (item['contentid'], item['contenttypeid']) 
            for item in items 
            if isinstance(item, dict) and 'title' in item
        }
        
        total_count = body.get('totalCount', 0)
        total_pages = math.ceil(total_count / ROWS_PER_PAGE)
        
        half_window = PAGE_WINDOW_SIZE // 2
        start_page = max(1, page_to_go - half_window)
        end_page = min(total_pages, start_page + PAGE_WINDOW_SIZE - 1)
        if end_page - start_page + 1 < PAGE_WINDOW_SIZE:
            start_page = max(1, end_page - PAGE_WINDOW_SIZE + 1)

        page_numbers_to_show = list(range(start_page, end_page + 1))

        radio_update = gr.update(choices=list(places_info.keys()), value=None)
        pagination_numbers_update = gr.update(choices=page_numbers_to_show, value=page_to_go)
        first_btn_update = gr.update(interactive=page_to_go > 1)
        prev_btn_update = gr.update(interactive=page_to_go > 1)
        next_btn_update = gr.update(interactive=page_to_go < total_pages)
        last_btn_update = gr.update(interactive=page_to_go < total_pages)
        pagination_row_update = gr.update(visible=total_pages > 1)

        return area_name, sigungu_name, category_name, page_to_go, total_pages, places_info, radio_update, pagination_numbers_update, first_btn_update, prev_btn_update, next_btn_update, last_btn_update, pagination_row_update

    except Exception as e:
        print(f"[update_page_view error] {e}")
        return area_name, sigungu_name, category_name, 1, 1, {}, gr.update(choices=[], value=None), gr.update(choices=[], value=None), gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False), gr.update(visible=False)