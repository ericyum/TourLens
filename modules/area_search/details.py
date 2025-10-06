import json
from datetime import date, timedelta
from utils import (
    common_params, session, BASE_URL, 
    format_json_to_clean_string, create_trend_plot
)
from modules.naver_search.naver_review import search_naver_blog, get_naver_trend

def get_details(selected_title, places_info):
    if not selected_title or not places_info:
        return "", "", "", "", "", ""
    
    if selected_title not in places_info:
        return "선택된 항목을 찾을 수 없습니다.", "", "", "", "", ""

    content_id, content_type_id = places_info[selected_title]
    results = [""] * 6
    apis_to_call = [("detailCommon2", {"contentId": content_id}), ("detailIntro2", {"contentId": content_id, "contentTypeId": content_type_id}), ("detailInfo2", {"contentId": content_id, "contentTypeId": content_type_id})]
    
    # 1. TourAPI 상세 정보 조회
    for i, (api_name, specific_params) in enumerate(apis_to_call):
        try:
            params = {**common_params, **specific_params}
            response = session.get(f"{BASE_URL}{api_name}", params=params)
            response.raise_for_status()
            
            if not response.text or not response.text.strip():
                raise ValueError("API 응답이 비어 있습니다.")

            response_json = response.json()
            
            header = response_json.get('response', {}).get('header', {})
            if header.get('resultCode') != '0000':
                pretty_output = json.dumps(response_json, indent=2, ensure_ascii=False)
            else:
                pretty_output = format_json_to_clean_string(response_json)

            results[i * 2] = json.dumps(response_json, indent=2, ensure_ascii=False)
            results[i * 2 + 1] = pretty_output

        except Exception as e:
            error_msg = f"{api_name} 처리 중 오류: {e}"
            results[i * 2] = error_msg
            results[i * 2 + 1] = f"정보를 가져오는 데 실패했습니다: {e}"

    # 2. 네이버 블로그 리뷰 검색 및 추가
    try:
        blog_query = f"{selected_title} 후기"
        blog_reviews = search_naver_blog(blog_query, display=3)
        
        if blog_reviews:
            blog_md = "\n\n---\n\n### 📝 네이버 블로그 리뷰\n\n"
            for review in blog_reviews:
                post_date = review.get('postdate', '')
                if post_date:
                    post_date = f"{post_date[0:4]}-{post_date[4:6]}-{post_date[6:8]}"

                blog_md += f"**[{review['title']}]({review['link']})** ({post_date})\n"
                blog_md += f"> {review['description']}...\n\n"
            
            results[1] += blog_md

    except Exception as e:
        print(f"네이버 블로그 리뷰 검색 중 오류: {e}")
        results[1] += "\n\n---\n\n블로그 리뷰를 가져오는 중 오류가 발생했습니다."

    # 3. 네이버 검색어 트렌드 그래프 추가
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        trend_data = get_naver_trend(selected_title, start_date, end_date)
        
        if trend_data:
            plot_path = create_trend_plot(trend_data, selected_title)
            if plot_path:
                trend_md = f"\n\n---\n\n### 📈 네이버 검색 트렌드\n\n![{selected_title} 트렌드]({plot_path})"
                results[1] += trend_md

    except Exception as e:
        print(f"네이버 트렌드 검색 중 오류: {e}")
        results[1] += "\n\n---\n\n트렌드 정보를 가져오는 중 오류가 발생했습니다."
            
    return tuple(results)