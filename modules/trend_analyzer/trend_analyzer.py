import os
import pandas as pd
import datetime
import matplotlib.pyplot as plt
import gradio as gr
import math
import traceback
import io
from PIL import Image # PIL 임포트 추가

from utils import common_params, session, BASE_URL, get_api_items, is_key_excluded
from modules.naver_search.naver_review import get_naver_trend, search_naver_blog
from modules.tour_api_search.area_search.controls import AREA_CODES, CONTENT_TYPE_CODES

# --- 신규 추가: 단일 아이템 분석 및 결과 반환 함수 ---
def analyze_single_item(keyword):
    """단일 키워드에 대해 트렌드 그래프와 블로그 후기를 분석하여 반환합니다."""
    if not keyword:
        return None, "분석할 키워드가 없습니다."

    # 1. 트렌드 분석 및 그래프 생성
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=90)
    trend_data = get_naver_trend(keyword, start_date, today)
    
    trend_image = None # 반환할 변수명을 image 객체로 변경
    if trend_data:
        try:
            plt.rcParams['font.family'] = 'Malgun Gothic'
            plt.rcParams['axes.unicode_minus'] = False
            df = pd.DataFrame(trend_data)
            df['period'] = pd.to_datetime(df['period'])
            df['ratio'] = df['ratio'].astype(float)

            plt.figure(figsize=(10, 5))
            plt.plot(df['period'], df['ratio'], marker='o', linestyle='-')
            plt.title(f"'{keyword}' 검색어 트렌드 (최근 90일)")
            plt.xlabel("날짜")
            plt.ylabel("상대적 검색량")
            plt.grid(True)
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            plt.close()
            buf.seek(0)
            trend_image = Image.open(buf) # Base64 대신 PIL Image 객체로 변환
        except Exception as e:
            print(f"트렌드 그래프 생성 중 오류: {e}")
            plt.close()

    # 2. 블로그 후기 검색
    blog_posts = search_naver_blog(keyword, display=3)
    reviews_markdown = "### 네이버 블로그 후기\n---"
    if blog_posts:
        for post in blog_posts:
            reviews_markdown += f"#### [{post['title']}]({post['link']})\n"
            reviews_markdown += f"> {post['description']}\n\n"
    else:
        reviews_markdown += "\n관련 블로그 후기를 찾을 수 없습니다.\n"

    return trend_image, reviews_markdown


# --- 범용 트렌드/후기 분석 함수 (파일 저장용) ---
def analyze_trends_for_titles(titles, progress=gr.Progress()):
    """주어진 제목 리스트에 대해 네이버 트렌드 및 블로그 후기 분석을 수행하고 결과를 저장합니다."""
    if not titles:
        return "분석할 관광지 이름이 없습니다."

    try:
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        print(f"폰트 설정 오류: {e}. 그래프의 한글이 깨질 수 있습니다.")

    trend_results = []
    review_results = [] # 후기 결과를 저장할 리스트
    today = datetime.date.today()
    trend_output_dir = r"C:\Users\SBA\github\TourLens\naver_trend"
    os.makedirs(trend_output_dir, exist_ok=True)

    for keyword in progress.tqdm(titles, total=len(titles), desc="관광지별 트렌드 및 후기 분석 중"):
        keyword = str(keyword).strip()
        if not keyword:
            continue

        # 1. 트렌드 분석
        start_date = today - datetime.timedelta(days=90)
        df_trend_data = get_naver_trend(keyword, start_date, today)

        if df_trend_data:
            df_trend = pd.DataFrame(df_trend_data)
            try:
                plt.figure(figsize=(10, 5))
                plt.plot(pd.to_datetime(df_trend['period']), df_trend['ratio'].astype(float), marker='o')
                plt.title(f"{keyword} 검색어 트렌드")
                plt.xlabel("날짜")
                plt.ylabel("검색량 지수")
                plt.grid(True)
                safe_keyword = "".join(c for c in keyword if c.isalnum() or c in (' ', '-')).rstrip()
                save_path = os.path.join(trend_output_dir, f"{safe_keyword}_trend.png")
                plt.savefig(save_path, dpi=150, bbox_inches="tight")
                plt.close()
            except Exception as e:
                print(f"'{keyword}' 그래프 저장 중 오류: {e}")
                plt.close()

            df_trend['keyword'] = keyword
            trend_results.append(df_trend)
        else:
            print(f"⚠️ '{keyword}'에 대한 트렌드 검색 결과가 없어 그래프를 생성하지 않습니다.")

        # 2. 블로그 후기 검색
        blog_posts = search_naver_blog(keyword, display=5)
        if blog_posts:
            for post in blog_posts:
                post['keyword'] = keyword # 어떤 키워드로 검색되었는지 추가
                review_results.append(post)

    # 3. 결과 저장
    output_messages = []
    if trend_results:
        final_trend_df = pd.concat(trend_results, ignore_index=True)
        final_trend_csv_path = os.path.join(trend_output_dir, "Seoul_Attractions_Trend.csv")
        final_trend_df.to_csv(final_trend_csv_path, index=False, encoding="utf-8-sig")
        output_messages.append(f"{len(trend_results)}개 항목의 트렌드 분석")
    
    if review_results:
        final_review_df = pd.DataFrame(review_results)
        final_review_csv_path = os.path.join(trend_output_dir, "Seoul_Attractions_Reviews.csv")
        final_review_df.to_csv(final_review_csv_path, index=False, encoding="utf-8-sig")
        output_messages.append(f"{len(review_results)}개 후기 수집")

    if not output_messages:
        return "트렌드 및 후기 분석을 수행할 항목이 없습니다."
    else:
        return f"분석 완료! {' / '.join(output_messages)}. 결과는 \"{trend_output_dir}\" 폴더에 저장되었습니다."


# --- 내부 헬퍼 함수: 파일 기반 트렌드 분석 실행 ---
def _run_analysis_from_file(tour_api_path, trend_output_dir, progress_tracker):
    try:
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        print(f"폰트 설정 오류: {e}. 그래프의 한글이 깨질 수 있습니다.")

    try:
        festival_df = pd.read_csv(tour_api_path, encoding="utf-8-sig")
        festival_df['eventstartdate'] = pd.to_datetime(festival_df['eventstartdate'], format="%Y%m%d", errors="coerce")
        festival_df['eventenddate'] = pd.to_datetime(festival_df['eventenddate'], format="%Y%m%d", errors="coerce")
    except FileNotFoundError:
        return f"오류: 중간 파일 {tour_api_path}를 찾을 수 없습니다."
    except Exception as e:
        return f"오류: 중간 CSV 파일을 읽는 중 문제가 발생했습니다: {e}"

    trend_results = []
    today = datetime.date.today()
    total_festivals = len(festival_df)

    for index, row in progress_tracker.tqdm(festival_df.iterrows(), total=total_festivals, desc="축제별 트렌드 분석 중"):
        keyword = str(row.get('title', '')).strip()
        start = row.get('eventstartdate')
        end = row.get('eventenddate')

        if not keyword or pd.isna(start) or pd.isna(end) or start.date() > today:
            continue

        start_for_api = (start - datetime.timedelta(days=30)).date()
        end_for_api = min((end + datetime.timedelta(days=30)).date(), today)

        df_trend_data = get_naver_trend(keyword, start_for_api, end_for_api)

        if df_trend_data is None or len(df_trend_data) == 0:
            print(f"⚠️ '{keyword}'에 대한 트렌드 검색 결과가 없어 그래프를 생성하지 않습니다.")
            continue

        df_trend = pd.DataFrame(df_trend_data)

        try:
            plt.figure(figsize=(10, 5))
            plt.plot(pd.to_datetime(df_trend['period']), df_trend['ratio'].astype(float), marker='o')
            plt.axvline(start, color='green', linestyle='--', label='행사 시작')
            plt.axvline(end, color='red', linestyle='--', label='행사 종료')
            plt.title(f"{keyword} 검색어 트렌드")
            plt.xlabel("날짜")
            plt.ylabel("검색량 지수")
            plt.legend()
            plt.grid(True)
            safe_keyword = "".join(c for c in keyword if c.isalnum() or c in (' ', '-')).rstrip()
            save_path = os.path.join(trend_output_dir, f"{safe_keyword}_trend.png")
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            plt.close()
        except Exception as e:
            print(f"'{keyword}' 그래프 저장 중 오류: {e}")
            plt.close()

        df_trend['keyword'] = keyword
        df_trend['eventstartdate'] = start
        df_trend['eventenddate'] = end
        trend_results.append(df_trend)

    if trend_results:
        final_trend_df = pd.concat(trend_results, ignore_index=True)
        final_csv_path = os.path.join(trend_output_dir, "Festival_Trend_WithPeriod.csv")
        final_trend_df.to_csv(final_csv_path, index=False, encoding="utf-8-sig")
        return f"분석 완료! {len(trend_results)}개 항목의 트렌드 분석 결과가 \"{trend_output_dir}\" 폴더에 저장되었습니다."
    else:
        return "트렌드 분석을 수행할 항목이 없습니다."

# --- 내부 헬퍼 함수: 아이템 목록의 전체 상세 정보 수집 ---
def _get_full_details_for_items(items_list, progress_tracker):
    all_item_details = []
    for item in progress_tracker.tqdm(items_list, desc="상세 정보 수집 중"):
        if not isinstance(item, dict):
            continue
        content_id = item.get('contentid')
        content_type_id = item.get('contenttypeid')
        if not content_id:
            all_item_details.append(item)
            continue

        base_data = item.copy()
        try:
            apis_to_process = [
                ("detailCommon2", {**common_params, "contentId": content_id, "defaultYN": "Y", "firstImageYN": "Y", "areacodeYN": "Y", "catcodeYN": "Y", "addrinfoYN": "Y", "mapinfoYN": "Y", "overviewYN": "Y"}),
                ("detailIntro2", {**common_params, "contentId": content_id, "contentTypeId": content_type_id}),
            ]
            for api_name, params in apis_to_process:
                response = session.get(f"{BASE_URL}{api_name}", params=params)
                if response.status_code == 200 and response.text:
                    res_items = get_api_items(response.json())
                    for res_item in res_items:
                        if isinstance(res_item, dict):
                            base_data.update(res_item)
            
            detail_info_params = {**common_params, "contentId": content_id, "contentTypeId": content_type_id}
            response = session.get(f"{BASE_URL}detailInfo2", params=detail_info_params)
            if response.status_code == 200 and response.text:
                info_items = get_api_items(response.json())
                if info_items and isinstance(info_items[0], dict):
                    base_data.update(info_items[0])
            all_item_details.append(base_data)
        except Exception as e:
            print(f"상세 정보 수집 중 오류 (content_id: {content_id}): {e}")
            all_item_details.append(base_data)
    return all_item_details

# --- "지역/카테고리별 검색" 탭을 위한 메인 함수 ---
def generate_trends_from_area_search(area_name, sigungu_name, category_name, progress=gr.Progress()):
    if not area_name:
        return "오류: 지역을 먼저 선택해주세요."

    try:
        # 1. 모든 아이템 목록 가져오기
        area_code = AREA_CODES.get(area_name)
        content_type_id = CONTENT_TYPE_CODES.get(category_name)
        count_params = {**common_params, "areaCode": area_code, "numOfRows": 1, "pageNo": 1}
        if sigungu_name and sigungu_name != "전체":
            sigungu_response = session.get(f"{BASE_URL}areaCode2", params={**common_params, "areaCode": area_code, "numOfRows": "100"})
            sigungu_items = get_api_items(sigungu_response.json())
            sigungu_code = next((item['code'] for item in sigungu_items if isinstance(item, dict) and item.get('name') == sigungu_name), None)
            if sigungu_code: count_params["sigunguCode"] = sigungu_code
        if content_type_id:
            count_params["contentTypeId"] = content_type_id

        response = session.get(f"{BASE_URL}areaBasedList2", params=count_params)
        response.raise_for_status()
        data = response.json()
        body = data.get('response', {}).get('body', {})
        total_count = body.get('totalCount', 0) if isinstance(body, dict) else 0

        if total_count == 0:
            return "분석할 데이터가 없습니다."

        all_items = []
        num_of_rows = 100
        total_pages = math.ceil(total_count / num_of_rows)
        list_params = {**count_params}
        for page_no in progress.tqdm(range(1, total_pages + 1), desc="관광지 목록 수집 중"):
            list_params.update({"numOfRows": num_of_rows, "pageNo": page_no})
            response = session.get(f"{BASE_URL}areaBasedList2", params=list_params)
            items = get_api_items(response.json())
            all_items.extend(items)

        # 2. 상세 정보 수집
        full_details = _get_full_details_for_items(all_items, progress)

        # 3. 중간 CSV 파일 저장을 위해 데이터 필터링
        filtered_details = []
        for item_dict in full_details:
            new_dict = {key: value for key, value in item_dict.items() if not is_key_excluded(key)}
            filtered_details.append(new_dict)

        tour_api_data_dir = r"C:\Users\SBA\github\TourLens\TourAPI_data"
        os.makedirs(tour_api_data_dir, exist_ok=True)
        intermediate_csv_path = os.path.join(tour_api_data_dir, "TourAPI_Festival.csv")
        pd.DataFrame(filtered_details).to_csv(intermediate_csv_path, index=False, encoding='utf-8-sig')

        # 4. 트렌드 분석 실행
        trend_output_dir = r"C:\Users\SBA\github\TourLens\naver_trend"
        return _run_analysis_from_file(intermediate_csv_path, trend_output_dir, progress)

    except Exception as e:
        traceback.print_exc()
        return f"오류 발생: {e}"

# --- "내 위치로 검색" 탭을 위한 메인 함수 ---
def generate_trends_from_location_search(places_info, progress=gr.Progress()):
    if not places_info:
        return "오류: 먼저 주변 관광지를 검색해주세요."

    items_to_process = []
    for title, (contentid, contenttypeid) in places_info.items():
        items_to_process.append({
            'title': title,
            'contentid': contentid,
            'contenttypeid': contenttypeid
        })

    # 2. 상세 정보 수집
    full_details = _get_full_details_for_items(items_to_process, progress)

    # 3. 중간 CSV 파일 저장을 위해 데이터 필터링
    filtered_details = []
    for item_dict in full_details:
        new_dict = {key: value for key, value in item_dict.items() if not is_key_excluded(key)}
        filtered_details.append(new_dict)

    tour_api_data_dir = r"C:\Users\SBA\github\TourLens\TourAPI_data"
    os.makedirs(tour_api_data_dir, exist_ok=True)
    intermediate_csv_path = os.path.join(tour_api_data_dir, "TourAPI_Festival.csv")
    pd.DataFrame(filtered_details).to_csv(intermediate_csv_path, index=False, encoding='utf-8-sig')

    # 4. 트렌드 분석 실행
    trend_output_dir = r"C:\Users\SBA\github\TourLens\naver_trend"
    return _run_analysis_from_file(intermediate_csv_path, trend_output_dir, progress)