import requests
import requests.adapters
import urllib3
import os
import re
from urllib.parse import quote
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64

# --- TourAPI 기본 설정 ---
class CustomAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = urllib3.util.ssl_.create_urllib3_context(ciphers='DEFAULT@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(CustomAdapter, self).init_poolmanager(*args, **kwargs)

TOUR_API_KEY = os.getenv("TOUR_API_KEY")
API_KEY = quote(TOUR_API_KEY) if TOUR_API_KEY else ""
BASE_URL = "https://apis.data.go.kr/B551011/KorService2/"
session = requests.Session()
session.mount("https://", CustomAdapter())

common_params = {
    "_type": "json",
    "MobileOS": "ETC",
    "MobileApp": "AppTest",
    "serviceKey": API_KEY
}

# --- 데이터 필터링 및 포맷팅 ---
EXCLUDED_KEYS = {
    'createdtime', 'modifiedtime', 'cpyrhtDivCd', 'areacode', 'sigungucode',
    'lDongRegnCd', 'lDongSignguCd', 'lclsSystm1', 'lclsSystm2', 'lclsSystm3',
    'zipcode', 'mapx', 'mapy', 'mlevel',
    'agelimit', 'bookingplace', 'placeinfo', 'subevent', 'program',
    'discountinfofestival', 'spendtimefestival', 'festivalgrade',
    'progresstype', 'festivaltype', 'serialnum', 'infoname', 'fldgubun'
}

def get_api_items(response_json):
    """TourAPI JSON 응답에서 item 리스트를 안전하게 추출합니다."""
    if not isinstance(response_json, dict):
        return []
    
    body = response_json.get('response', {}).get('body', {})
    if not isinstance(body, dict):
        return []
        
    items_container = body.get('items', {})
    if not isinstance(items_container, dict):
        return []
        
    items = items_container.get('item', [])
    
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        return items
        
    return []

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def is_key_excluded(key):
    if key == 'eventenddate':
        return False
    if not key: return True
    return 'id' in key.lower() or key.lower().startswith('cat') or key in EXCLUDED_KEYS

def format_json_to_clean_string(json_data):
    """JSON 데이터를 필터링하고 사람이 읽기 쉬운 마크다운 문자열로 변환합니다."""
    items = get_api_items(json_data)
    if not items:
        return "표시할 정보가 없습니다."

    output_lines = []
    homepage_regex = "href=([\"'])(.*?)\\1"

    for item in items:
        image_keys = ['firstimage', 'firstimage2']
        for key in image_keys:
            value = item.get(key)
            if value and 'http' in str(value):
                output_lines.append(f"![{key}]({value})")
        
        for key, value in item.items():
            if key in image_keys: continue

            if not is_key_excluded(key) and value and str(value).strip():
                cleaned_value = ""
                if key == 'homepage':
                    match = re.search(homepage_regex, str(value))
                    cleaned_value = match.group(2) if match else clean_html(str(value))
                else:
                    cleaned_value = clean_html(str(value))
                
                if cleaned_value:
                    output_lines.append(f"**{key}**: {cleaned_value}")
        output_lines.append("---")
    
    if output_lines:
        output_lines.pop()

    return "\n\n".join(output_lines) if output_lines else "표시할 정보가 없습니다."

# --- 트렌드 그래프 생성 ---
def create_trend_plot(trend_data, keyword):
    """트렌드 데이터로 그래프를 그리고 Base64 데이터 URI를 반환합니다."""
    if not trend_data:
        return None
    
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

        # 이미지를 메모리 버퍼에 저장
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0);

        # Base64로 인코딩하여 데이터 URI 생성
        data = base64.b64encode(buf.read()).decode('utf-8')
        return f"data:image/png;base64,{data}"

    except Exception as e:
        print(f"트렌드 그래프 생성 중 오류: {e}")
        plt.close()
        return None
