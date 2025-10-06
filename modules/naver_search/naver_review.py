import requests
import os
import re
import json
from datetime import date, timedelta

# .env 파일에서 네이버 API 키 로드
# 블로그 검색 API
NAVER_BLOG_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_BLOG_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 데이터랩 트렌드 API
NAVER_TREND_CLIENT_ID = os.getenv("NAVER_TREND_CLIENT_ID")
NAVER_TREND_CLIENT_SECRET = os.getenv("NAVER_TREND_CLIENT_SECRET")

def clean_html(raw_html):
    """HTML 태그를 제거하는 간단한 함수"""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def search_naver_blog(query, display=5):
    """네이버 블로그 검색 API를 호출하고 결과를 반환합니다."""
    if not NAVER_BLOG_CLIENT_ID or not NAVER_BLOG_CLIENT_SECRET:
        print("네이버 블로그 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        return []

    headers = {
        "X-Naver-Client-Id": NAVER_BLOG_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_BLOG_CLIENT_SECRET,
    }
    
    params = {
        "query": query,
        "display": display,
        "sort": "sim"  # 관련도순 정렬
    }

    try:
        response = requests.get("https://openapi.naver.com/v1/search/blog.json", headers=headers, params=params)
        response.raise_for_status()  # 오류 발생 시 예외 처리
        
        data = response.json()
        
        results = []
        for item in data.get("items", []):
            results.append({
                "title": clean_html(item.get("title", "")),
                "description": clean_html(item.get("description", "")),
                "link": item.get("link", ""),
                "postdate": item.get("postdate", "")
            })
        return results

    except requests.exceptions.RequestException as e:
        print(f"네이버 블로그 API 호출 오류: {e}")
        return []
    except Exception as e:
        print(f"블로그 데이터 처리 중 오류: {e}")
        return []

def get_naver_trend(keyword, start_date, end_date):
    """네이버 데이터랩 검색어 트렌드 API를 호출하고 결과를 반환합니다."""
    if not NAVER_TREND_CLIENT_ID or not NAVER_TREND_CLIENT_SECRET:
        print("네이버 트렌드 API 인증 정보가 .env 파일에 설정되지 않았습니다.")
        return None

    headers = {
        "X-Naver-Client-Id": NAVER_TREND_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_TREND_CLIENT_SECRET,
        "Content-Type": "application/json"
    }

    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": "date",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }

    try:
        response = requests.post("https://openapi.naver.com/v1/datalab/search", headers=headers, data=json.dumps(body))
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('results') or not data['results'][0].get('data'):
            # print(f"'{keyword}'에 대한 트렌드 검색 결과가 없습니다.") # 로그가 너무 많이 찍히므로 주석 처리
            return None
            
        return data['results'][0]['data']

    except requests.exceptions.RequestException as e:
        print(f"네이버 트렌드 API 호출 오류: {e}")
        return None
    except Exception as e:
        print(f"트렌드 데이터 처리 중 오류: {e}")
        return None
