# 📸 TourLens

**AI와 함께 떠나는 스마트한 여행 정보 탐색기, TourLens**

TourLens는 흩어져 있는 국내 관광 정보를 한곳에 모아, 사용자의 위치와 관심사에 맞춰 최적의 여행지를 추천하고 트렌드 분석까지 제공하는 웹 애플리케이션입니다.

## ✨ 주요 기능

-   **📍 내 위치 기반 검색**: 현재 내 위치를 기준으로 주변의 관광지를 간편하게 찾아봅니다.
-   **🗺️ 지역/카테고리별 검색**: 원하는 지역과 관심사(관광지, 맛집, 숙소 등)를 선택하여 맞춤 정보를 검색합니다. (한국관광공사 TourAPI 활용)
-   **🏙️ 서울시 관광지 특화 검색**: 서울시가 제공하는 방대한 관광 데이터를 카테고리별로 상세하게 탐색합니다.
-   **📈 트렌드 분석**: 검색된 장소나 키워드의 네이버 검색량 트렌드를 그래프로 시각화하여 인기도를 파악할 수 있습니다.
-   **✍️ 블로그 리뷰 요약**: 네이버 블로그의 최신 후기를 분석하여 긍정/부정 리뷰를 요약해 보여줍니다.
-   **📊 데이터 내보내기**: 검색 결과를 CSV 파일로 다운로드하여 나만의 여행 데이터를 만들 수 있습니다.

## 🖼️ 데모

*(여기에 TourLens 실행 화면 스크린샷이나 GIF를 추가하면 프로젝트를 이해하는 데 큰 도움이 됩니다.)*

![TourLens Demo](https://user-images.githubusercontent.com/example.png)

## 🛠️ 기술 스택

-   **Framework**: Gradio
-   **APIs**:
    -   한국관광공사 TourAPI
    -   서울시 관광정보 API
    -   Naver Search Trend API
    -   Naver Blog Search API
-   **Libraries**: Pandas, Matplotlib, etc.
-   **Language**: Python

## ⚙️ 설치 및 실행 방법

1.  **프로젝트 클론**
    ```bash
    git clone https://github.com/langchain-kr/TourLens.git
    cd TourLens
    ```

2.  **필요한 라이브러리 설치**
    ```bash
    pip install -r requirements.txt
    ```
    *(만약 `requirements.txt` 파일이 없다면, `pip install gradio pandas matplotlib python-dotenv requests` 명령어로 주요 라이브러리를 설치하세요.)*

3.  **API 키 설정**

    프로젝트 루트 디렉터리에 `.env` 파일을 생성하고, 아래와 같이 필요한 API 키를 입력하세요.

    ```
    # 한국관광공사 TourAPI 키 (선택)
    # TOUR_API_KTY="YOUR_TOUR_API_KEY"

    # 네이버 API 인증 정보 (필수)
    NAVER_CLIENT_ID="YOUR_NAVER_CLIENT_ID"
    NAVER_CLIENT_SECRET="YOUR_NAVER_CLIENT_SECRET"

    # 네이버 데이터랩 API 인증 정보 (필수)
    NAVER_TREND_CLIENT_ID="YOUR_NAVER_TREND_CLIENT_ID"
    NAVER_TREND_CLIENT_SECRET="YOUR_NAVER_TREND_CLIENT_SECRET"
    ```

4.  **애플리케이션 실행**
    ```bash
    python app.py
    ```

5.  웹 브라우저에서 `http://127.0.0.1:7860` 주소로 접속합니다.

## 📂 프로젝트 구조

```
TourLens/
├── .env              # API 키 저장 파일
├── app.py            # Gradio 메인 애플리케이션
├── utils.py          # API 호출, 데이터 포맷팅 등 유틸리티 함수
├── modules/          # 기능별 모듈
│   ├── area_search/    # 지역/카테고리 검색 관련 모듈
│   ├── location_search/# 내 위치 기반 검색 관련 모듈
│   ├── seoul_search/   # 서울시 API 검색 관련 모듈
│   ├── naver_review.py # 네이버 블로그 리뷰 분석 모듈
│   └── trend_analyzer.py # 네이버 트렌드 분석 모듈
└── README.md         # 프로젝트 소개 파일
```
