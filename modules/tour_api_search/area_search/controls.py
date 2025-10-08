import gradio as gr
from utils import common_params, session, BASE_URL, get_api_items

AREA_CODES = {
    "서울": 1, "인천": 2, "대전": 3, "대구": 4, "광주": 5, "부산": 6, "울산": 7, "세종": 8,
    "경기도": 31, "강원도": 32, "충청북도": 33, "충청남도": 34, "경상북도": 35, "경상남도": 36,
    "전라북도": 37, "전라남도": 38, "제주도": 39
}
CONTENT_TYPE_CODES = {
    "전체": None, "관광지": "12", "문화시설": "14", "행사/공연/축제": "15",
    "여행코스": "25", "레포츠": "28", "숙박": "32", "쇼핑": "38", "음식점": "39"
}

def update_sigungu_dropdown(area_name):
    if not area_name: return gr.update(choices=[], interactive=False)
    try:
        area_code = AREA_CODES.get(area_name)
        params = {**common_params, "areaCode": area_code, "numOfRows": "100"}
        response = session.get(f"{BASE_URL}areaCode2", params=params)
        response.raise_for_status()
        
        items = get_api_items(response.json())
        
        sigungu_names = [item['name'] for item in items if isinstance(item, dict) and 'name' in item]
        
        return gr.update(choices=["전체"] + sigungu_names, value="전체", interactive=True)
    except Exception as e:
        print(f"[update_sigungu_dropdown error] {e}")
        return gr.update(choices=[], interactive=False)