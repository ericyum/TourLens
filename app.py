import gradio as gr
import os
from dotenv import load_dotenv
import glob

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

# --- 모듈에서 각 탭의 UI 생성 함수들을 가져옴 ---
from modules.tour_api_search.ui import create_api_search_tab
from modules.naver_search.ui import create_naver_search_tab
from modules.seoul_search.ui import create_seoul_search_ui
from modules.tour_api_playwright_search.ui import create_tour_api_playwright_tab

# --- Gradio TabbedInterface를 사용하여 전체 UI 구성 ---
demo = gr.TabbedInterface(
    [create_api_search_tab(), create_seoul_search_ui(), create_naver_search_tab(), create_tour_api_playwright_tab()],
    tab_names=["Tour API 조회(API)", "서울시 관광지 검색", "네이버 검색", "Tour API 직접 조회 (Playwright)"],
    title="TourLens 관광 정보 앱"
)

# --- 애플리케이션 실행 ---
if __name__ == "__main__":
    # .env 파일 및 필수 키 확인
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
