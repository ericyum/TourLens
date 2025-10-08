import gradio as gr
import math
import csv
import io
import tempfile
import re
import traceback
from utils import common_params, session, BASE_URL, clean_html, is_key_excluded, get_api_items
from modules.tour_api_search.area_search.controls import AREA_CODES, CONTENT_TYPE_CODES

def export_to_csv(area_name, sigungu_name, category_name, progress=gr.Progress()):
    """검색된 모든 결과를 API 응답 순서에 따른 동적 컬럼 CSV 파일로 저장합니다."""
    if not area_name:
        gr.Warning("지역을 먼저 선택해주세요.")
        return None

    progress(0, desc="전체 데이터 개수 확인 중...")

    try:
        # 1. 전체 아이템 개수 확인
        area_code = AREA_CODES.get(area_name)
        content_type_id = CONTENT_TYPE_CODES.get(category_name)
        
        base_list_params = {**common_params, "areaCode": area_code, "numOfRows": 1, "pageNo": 1}
        if sigungu_name and sigungu_name != "전체":
            sigungu_response = session.get(f"{BASE_URL}areaCode2", params={**common_params, "areaCode": area_code, "numOfRows": "100"})
            sigungu_response.raise_for_status()
            sigungu_items = get_api_items(sigungu_response.json())
            sigungu_code = next((item['code'] for item in sigungu_items if isinstance(item, dict) and item.get('name') == sigungu_name), None)
            if sigungu_code: base_list_params["sigunguCode"] = sigungu_code
        if content_type_id:
            base_list_params["contentTypeId"] = content_type_id

        response = session.get(f"{BASE_URL}areaBasedList2", params=base_list_params)
        response.raise_for_status()
        data = response.json()
        body = data.get('response', {}).get('body', {})
        total_count = body.get('totalCount', 0) if isinstance(body, dict) else 0

        if total_count == 0:
            gr.Info("내보낼 데이터가 없습니다.")
            return None

        # 2. 모든 기본 아이템 정보 수집
        all_basic_items = []
        num_of_rows = 100
        total_pages = math.ceil(total_count / num_of_rows)
        
        for page_no in progress.tqdm(range(1, total_pages + 1), desc="관광지 목록 수집 중"):
            base_list_params.update({"numOfRows": num_of_rows, "pageNo": page_no})
            response = session.get(f"{BASE_URL}areaBasedList2", params=base_list_params)
            response.raise_for_status()
            items = get_api_items(response.json())
            all_basic_items.extend(items)

        # 3. 각 아이템의 상세 정보 조회 및 데이터 재구성
        all_item_details = []
        ordered_headers = []
        seen_keys = set()

        def add_key_to_header(key):
            if is_key_excluded(key):
                return
            if key not in seen_keys:
                ordered_headers.append(key)
                seen_keys.add(key)

        for item in progress.tqdm(all_basic_items, desc="상세 정보 조회 및 데이터 구성 중"):
            if not isinstance(item, dict):
                continue

            content_id = item.get('contentid')
            content_type_id = item.get('contenttypeid')
            if not content_id:
                continue

            base_data = {}
            try:
                base_data.update(item)
                for key in item.keys():
                    add_key_to_header(key)

                apis_to_process = [
                    ("detailCommon2", {**common_params, "contentId": content_id, "defaultYN": "Y", "firstImageYN": "Y", "areacodeYN": "Y", "catcodeYN": "Y", "addrinfoYN": "Y", "mapinfoYN": "Y", "overviewYN": "Y"}),
                    ("detailIntro2", {**common_params, "contentId": content_id, "contentTypeId": content_type_id}),
                ]

                for api_name, params in apis_to_process:
                    response = session.get(f"{BASE_URL}{api_name}", params=params)
                    response.raise_for_status()
                    if not response.text or not response.text.strip(): continue
                    
                    res_items = get_api_items(response.json())

                    for res_item in res_items:
                        if isinstance(res_item, dict):
                            base_data.update(res_item)
                            for key in res_item.keys():
                                add_key_to_header(key)
                
                detail_info_params = {**common_params, "contentId": content_id, "contentTypeId": content_type_id}
                response = session.get(f"{BASE_URL}detailInfo2", params=detail_info_params)
                response.raise_for_status()
                
                info_items = get_api_items(response.json())

                if info_items:
                    for info_item in info_items:
                        if isinstance(info_item, dict):
                            row_data = {**base_data, **info_item}
                            all_item_details.append(row_data)
                            for key in info_item.keys():
                                add_key_to_header(key)
                else:
                    all_item_details.append(base_data)

            except Exception as detail_e:
                print(f"Error fetching details for content_id {content_id}: {detail_e}")
                continue
        
        if not all_item_details:
            gr.Info("상세 정보를 가져올 수 있는 데이터가 없습니다.")
            return None

        # 4. CSV 파일 생성
        progress(0.9, desc="CSV 파일 생성 중...")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=ordered_headers, extrasaction='ignore')
        writer.writeheader()

        for item_data in all_item_details:
            cleaned_item = {}
            for k, v in item_data.items():
                if k == 'homepage':
                    match = re.search(r'href=["\\](["\\]+)[\"\\]', str(v))
                    cleaned_item[k] = match.group(1) if match else clean_html(str(v))
                else:
                    cleaned_item[k] = clean_html(v) if isinstance(v, str) else v
            writer.writerow(cleaned_item)
        
        csv_content = output.getvalue()
        output.close()
        
        encoded_content = csv_content.encode('utf-8-sig')

        with tempfile.NamedTemporaryFile(delete=False, mode='wb', suffix='.csv', prefix='tour_data_') as temp_f:
            temp_f.write(encoded_content)
            gr.Info("CSV 파일 생성이 완료되었습니다. 아래 링크를 클릭하여 다운로드하세요.")
            return temp_f.name

    except Exception as e:
        import traceback
        print(f"[export_to_csv error] {e}")
        traceback.print_exc()
        gr.Error(f"CSV 생성 중 오류가 발생했습니다: {e}")
        return None