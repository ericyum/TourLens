import gradio as gr
import json
import asyncio
import os
import requests
import shutil
from playwright.async_api import async_playwright
from modules.naver_search.naver_review import search_naver_blog
from langchain_openai import ChatOpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import nltk
from nltk.tokenize import sent_tokenize

# NLTK 문장 토크나이저 다운로드 (최초 1회 실행 필요)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')


# --- 블로그 스크래핑 ---
async def scrape_blog_content(url: str) -> tuple[str, list[str]]:
    """
    Playwright를 사용하여 주어진 URL의 블로그 본문 텍스트와 이미지 URL들을 스크래핑합니다.
    """
    text_content = ""
    image_urls = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)

            main_frame = page
            try:
                main_frame_element = await page.wait_for_selector(
                    "iframe#mainFrame", timeout=5000
                )
                main_frame = await main_frame_element.content_frame()
                if main_frame is None:
                    main_frame = page
            except Exception:
                main_frame = page

            content_selectors = [
                "div.se-main-container",
                "div.post-view",
                "#postViewArea",
            ]
            content_element = None
            for selector in content_selectors:
                try:
                    await main_frame.wait_for_selector(selector, timeout=5000)
                    content_element = await main_frame.query_selector(selector)
                    if content_element:
                        text_content = await content_element.inner_text()
                        if text_content.strip():
                            # 이미지 찾기
                            images = await content_element.query_selector_all("img")
                            for img in images:
                                # 네이버 블로그는 lazy loading을 사용하므로 data-lazy-src, data-src, src 순으로 확인
                                lazy_src = await img.get_attribute("data-lazy-src")
                                data_src = await img.get_attribute("data-src")
                                regular_src = await img.get_attribute("src")

                                src = lazy_src or data_src or regular_src

                                if (
                                    src
                                    and src.startswith("http")
                                    and "storep-phinf.pstatic.net" not in src
                                ):
                                    # 썸네일 파라미터(?type=...)를 제거하여 원본 이미지 URL 확보
                                    cleaned_src = src.split("?")[0]
                                    if cleaned_src not in image_urls:
                                        image_urls.append(cleaned_src)
                            break  # 내용과 이미지를 찾았으면 중단
                except Exception:
                    continue

            await browser.close()

            if not text_content.strip():
                return (
                    "본문 내용을 찾을 수 없습니다. (지원되지 않는 블로그 구조일 수 있습니다)",
                    [],
                )

            return text_content, image_urls

    except Exception as e:
        return f"페이지에 접근하는 중 오류가 발생했습니다: {e}", []


# --- 메인 검색 및 스크래핑 함수 ---
async def search_naver_reviews_and_scrape(
    keyword, progress=gr.Progress(track_tqdm=True)
):
    """
    네이버 블로그를 검색(10개)하고, 각 결과의 본문과 이미지를 스크래핑하여 로컬에 저장합니다.
    """
    # --- 이미지 저장 폴더 설정 및 초기화 ---
    image_save_dir = os.path.join(os.path.dirname(__file__), "naver_search_png")
    if os.path.exists(image_save_dir):
        shutil.rmtree(image_save_dir)
    os.makedirs(image_save_dir, exist_ok=True)

    if not keyword:
        return "{}", "키워드를 입력해주세요.", [], []

    progress(0, desc="네이버 블로그 검색 중...")
    blog_reviews = search_naver_blog(keyword, display=10)

    if not blog_reviews:
        return "{}", f"'{keyword}'에 대한 네이버 블로그 검색 결과가 없습니다.", [], []

    tasks = []
    for review in blog_reviews:
        link = review.get("link")
        if link and "blog.naver.com" in link:
            tasks.append(scrape_blog_content(link))
        else:

            async def get_empty_result():
                return ("네이버 블로그가 아니므로 내용을 가져오지 않습니다.", [])

            tasks.append(get_empty_result())

    progress(0.5, desc=f"{len(tasks)}개의 블로그 본문 및 이미지 스크래핑 중...")
    scraped_results = await asyncio.gather(*tasks)

    scraped_reviews = []
    all_image_urls = []
    for i, review in enumerate(blog_reviews):
        text_content, image_urls = scraped_results[i]
        review["content"] = text_content
        scraped_reviews.append(review)
        all_image_urls.extend(image_urls)

    # --- 스크래핑된 이미지 다운로드 ---
    progress(0.8, desc=f"{len(all_image_urls)}개 이미지 다운로드 중...")
    local_image_paths = []
    for i, img_url in enumerate(all_image_urls):
        try:
            response = requests.get(img_url, stream=True, timeout=10)
            response.raise_for_status()

            # 파일 확장자 추출 (없으면 .jpg 사용)
            file_ext = os.path.splitext(img_url.split("?")[0])[-1]
            if not file_ext or len(file_ext) > 5:  # 간단한 유효성 검사
                file_ext = ".jpg"

            file_name = f"image_{i+1}{file_ext}"
            file_path = os.path.join(image_save_dir, file_name)

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            local_image_paths.append(file_path)
        except requests.exceptions.RequestException as e:
            print(f"이미지 다운로드 실패: {img_url}, 오류: {e}")
            continue

    progress(1, desc="완료")

    raw_json_output = json.dumps(scraped_reviews, indent=2, ensure_ascii=False)

    formatted_output_lines = [f"### '{keyword}' 네이버 블로그 검색 및 스크래핑 결과\n"]
    for review in scraped_reviews:
        post_date = review.get("postdate", "")
        if post_date:
            post_date = f"{post_date[0:4]}-{post_date[4:6]}-{post_date[6:8]}"

        title = review.get("title", "제목 없음").replace("[", "\[").replace("]", "\]")
        link = review.get("link", "#")
        description = (
            review.get("description", "내용 없음").replace("[", "\[").replace("]", "\]")
        )
        content = review.get("content", "본문 없음")

        formatted_output_lines.append(f"**[{title}]({link})** ({post_date})")
        formatted_output_lines.append(f"> {description}...\n")
        formatted_output_lines.append("#### 블로그 본문")
        formatted_output_lines.append(f"```\n{content}\n```\n")

    formatted_output = "\n".join(formatted_output_lines)

    return raw_json_output, formatted_output, scraped_reviews, local_image_paths


# --- OpenAI (GPT) 요약 함수 ---
def summarize_blog_contents_stream(reviews_data, progress=gr.Progress(track_tqdm=True)):
    """
    스크래핑된 블로그 본문을 1차 요약 후, 2차로 주관적인 내용만 필터링하여 스트리밍합니다.
    """
    if not reviews_data:
        yield "요약할 내용이 없습니다."
        return

    progress(0, desc="OpenAI API로 1차 요약 준비 중...")

    if "OPENAI_API_KEY" not in os.environ:
        yield "오류: OPENAI_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인해주세요."
        return

    try:
        gpt = ChatOpenAI(temperature=0, model_name="gpt-4.1-mini")
    except Exception as e:
        yield f"ChatOpenAI 모델 초기화 중 오류 발생: {e}"
        return

    full_text = ""
    for i, review in enumerate(reviews_data):
        content = review.get("content", "")
        if (
            "본문 내용을 찾을 수 없습니다" in content
            or "페이지에 접근하는 중 오류" in content
        ):
            continue
        full_text += f"--- 블로그 후기 {i+1} ---\n\n{content}\n\n"

    if not full_text.strip():
        yield "요약할 유효한 블로그 본문이 없습니다."
        return

    # 1. 1차 요약 프롬프트
    initial_prompt = f"""
    다음은 하나의 주제에 대한 여러 네이버 블로그 후기 내용입니다.
    이 후기들을 종합하여 해당 주제(행사, 장소 등)의 주요 특징, 방문객들의 전반적인 반응, 긍정적인 점과 아쉬운 점을 중심으로 상세하게 요약해주세요.
    특히, 방문객들이 해당 행사를 즐긴 후 근처의 다른 음식점, 카페, 볼거리, 즐길거리 등을 이어서 방문했다는 내용이 있다면 그 부분도 놓치지 말고 요약에 포함해주세요.
    각 블로그의 내용을 단순히 나열하는 것이 아니라, 전체적인 관점에서 정보를 종합하고 재구성하여 전달해야 합니다.

    --- 전체 후기 내용 ---
    {full_text}
    ---
    
    위 내용을 바탕으로 상세 요약:
    """

    progress(0.2, desc="GPT가 1차 요약 중입니다...")

    try:
        # 1차 요약 (스트리밍 없이 내부적으로 완료)
        initial_summary = gpt.invoke(initial_prompt).content
    except Exception as e:
        yield f"OpenAI API 1차 요약 중 오류가 발생했습니다: {e}"
        return

    progress(0.6, desc="GPT가 2차 필터링 및 요약 중입니다...")

    # 2. 2차 필터링 및 요약 프롬프트
    filtering_prompt = f"""
    아래는 여러 블로그 후기를 바탕으로 생성된 1차 요약본입니다.
    이 요약본에서, 공식 관광 사이트에서는 얻기 힘든 '실제 방문객들의 주관적인 경험'과 관련된 내용만을 추출해주세요.

    추출한 내용을 다음 소주제들에 맞춰 최대한 상세하고 다양하게 분류하고 정리해주세요. 각 소주제에 해당하는 내용이 없다면 그 소주제는 결과에서 생략해주세요.

    - **추천 방문 대상 (누구와 함께 가면 좋을까?)**: (예: "커플 데이트 코스로 완벽해요", "아이들과 함께라면 교육적이고 즐거워요")
    - **가성비 및 만족도 (비용 대비 경험)**: (예: "입장료가 아깝지 않았어요", "무료인데도 볼거리가 풍성해서 만족도 높았어요")
    - **혼잡도 및 체감 대기 시간**: (예: "주말 오후에 방문했더니 사람이 너무 많아 제대로 보기 힘들었어요")
    - **추천 방문 시간대 및 요일**: (예: "야간 개장 때 조명이 켜지니 분위기가 훨씬 좋았어요")
    - **날씨별 방문 팁 (날씨가 경험에 미치는 영향)**: (예: "비 오는 날 방문하니 한옥의 운치가 더해져 좋았어요")
    - **어린이/가족 특화 정보**: (예: "유모차 끌고 다니기 편했어요", "수유실이 잘 되어있어요")
    - **편의시설 및 청결도**: (예: "화장실이 깨끗하고 관리가 잘 되어 있었어요")
    - **현장 직원 및 안내 친절도**: (예: "안내해주시는 분이 정말 친절하고 설명도 잘해주셔서 이해하기 쉬웠어요")
    - **기념품 및 굿즈 후기**: (예: "여기서만 살 수 있는 특별한 기념품이 많아요")
    - **놓치기 쉬운 숨은 팁 (아는 사람만 아는 꿀팁)**: (예: "입구 팸플릿 뒷면의 할인 쿠폰을 꼭 챙기세요")
    - **방문 전 기대치 vs 실제 경험**: (예: "SNS 사진만 보고 갔는데 생각보다 규모가 작아서 실망했어요")
    - **재방문 의사 및 추천 지수**: (예: "내년에도 꼭 다시 방문하고 싶어요")
    - **교육적 가치 및 정보성**: (예: "건축에 대해 몰랐던 새로운 사실을 많이 알게 되어 유익했어요")
    - **유사 행사/장소와의 비교**: (예: "작년 행사보다 프로그램이 더 다채로워졌어요")
    - **행사장 내 동선 및 이동 편의성**: (예: "전시관 사이의 거리가 멀지 않아 둘러보기 편했어요")
    - **현장 이벤트 및 체험 프로그램 상세 후기**: (예: "건축가와의 대화 프로그램이 가장 인상 깊었어요")
    - **행사장 분위기 (BGM, 조명 등)**: (예: "잔잔한 국악 배경음악이 한옥 분위기와 잘 어울렸어요")
    - **어르신/장애인 접근성**: (예: "계단이 많아서 거동이 불편하신 부모님이 힘들어하셨어요")
    - **외국인 방문객 시선**: (예: "영문 설명이 부족해서 아쉬웠어요")
    - **총평: 이 행사를 한 문장으로 요약한다면?**: (블로거가 내린 핵심적인 한 줄 평)

    공식 정보(행사 기간, 장소, 프로그램 목록, 가격 등)는 모두 제외하고, 오직 방문객들의 목소리가 담긴 내용만을 뽑아서 위의 형식에 맞춰 새롭게 정리해주세요.

    --- 1차 요약본 ---
    {initial_summary}
    ---

    --- 방문객 경험 중심 요약 (소주제별 분류) ---
    """

    try:
        # 2차 요약 (스트리밍)
        answer_stream = gpt.stream(filtering_prompt)

        full_filtered_summary = ""
        for chunk in answer_stream:
            full_filtered_summary += chunk.content
            yield full_filtered_summary

        progress(1, desc="요약 완료")

    except Exception as e:
        yield f"OpenAI API 2차 요약 중 오류가 발생했습니다: {e}"


# --- 챗봇 답변 생성 함수 (LLM 기반 스트리밍) ---
def answer_question_from_reviews_stream(question: str, reviews_data: list):
    """
    ChatOpenAI(LLM)를 사용하여 블로그 리뷰 내용 기반으로 질문에 답변하고 결과를 스트리밍합니다.
    """
    if not question:
        yield "질문을 입력해주세요."
        return
    if not reviews_data:
        yield "답변을 찾을 수 있는 블로그 후기 내용이 없습니다."
        return

    # 1. LLM 모델 초기화
    if "OPENAI_API_KEY" not in os.environ:
        yield "오류: OPENAI_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인해주세요."
        return
    try:
        gpt = ChatOpenAI(temperature=0, model_name="gpt-4.1-mini")
    except Exception as e:
        yield f"ChatOpenAI 모델 초기화 중 오류 발생: {e}"
        return

    # 2. 컨텍스트로 사용할 블로그 본문 전체 합치기
    full_text = ""
    for i, review in enumerate(reviews_data):
        content = review.get("content", "")
        if "본문 내용을 찾을 수 없습니다" in content or "페이지에 접근하는 중 오류" in content:
            continue
        full_text += f"--- 블로그 후기 {i+1} ---\n\n{content}\n\n"

    if not full_text.strip():
        yield "답변을 생성할 유효한 블로그 본문이 없습니다."
        return

    # 3. LLM에 전달할 프롬프트 구성
    prompt = f"""
    당신은 다음 '블로그 후기 모음' 내용을 완벽하게 숙지한 친절한 안내원입니다.
    사용자의 '질문'에 대해, 반드시 '블로그 후기 모음' 안에서만 근거를 찾아 답변해야 합니다.
    후기 내용에 질문에 대한 정보가 명확하게 없는 경우, "후기 내용만으로는 알 수 없습니다."라고 솔직하게 답변해주세요.
    절대로 당신의 기존 지식을 사용하거나 정보를 추측해서는 안 됩니다.

    --- 블로그 후기 모음 ---
    {full_text}
    ---

    사용자의 질문: "{question}"

    --- 답변 (블로그 후기 기반) ---
    """

    # 4. LLM 스트리밍 호출 및 결과 반환
    try:
        answer_stream = gpt.stream(prompt)

        full_answer = ""
        for chunk in answer_stream:
            full_answer += chunk.content
            yield full_answer
            
    except Exception as e:
        yield f"챗봇 답변 생성 중 오류가 발생했습니다: {e}"
