import gradio as gr
import json
import asyncio
import os
from playwright.async_api import async_playwright
from modules.naver_review import search_naver_blog
from langchain_openai import ChatOpenAI

# --- 블로그 스크래핑 ---
async def scrape_blog_content(url: str) -> str:
    """
    Playwright를 사용하여 주어진 URL의 블로그 본문 내용을 스크래핑합니다.
    iframe을 포함한 여러 네이버 블로그 구조에 대응합니다.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)

            main_frame = page
            try:
                main_frame_element = await page.wait_for_selector("iframe#mainFrame", timeout=5000)
                main_frame = await main_frame_element.content_frame()
                if main_frame is None: main_frame = page
            except Exception:
                main_frame = page

            content_selectors = ["div.se-main-container", "div.post-view", "#postViewArea"]
            text_content = ""
            for selector in content_selectors:
                try:
                    await main_frame.wait_for_selector(selector, timeout=5000)
                    content_element = await main_frame.query_selector(selector)
                    if content_element:
                        text_content = await content_element.inner_text()
                        if text_content.strip(): break
                except Exception:
                    continue

            await browser.close()

            if text_content.strip():
                return text_content
            else:
                return "본문 내용을 찾을 수 없습니다. (지원되지 않는 블로그 구조일 수 있습니다)"
    except Exception as e:
        return f"페이지에 접근하는 중 오류가 발생했습니다: {e}"

# --- 메인 검색 및 스크래핑 함수 ---
async def search_naver_reviews_and_scrape(keyword, progress=gr.Progress(track_tqdm=True)):
    """
    네이버 블로그를 검색(10개)하고, 각 결과의 본문을 Playwright로 스크래핑합니다.
    """
    if not keyword:
        return "{}", "키워드를 입력해주세요.", []

    progress(0, desc="네이버 블로그 검색 중...")
    blog_reviews = search_naver_blog(keyword, display=10)

    if not blog_reviews:
        return "{}", f"'{keyword}'에 대한 네이버 블로그 검색 결과가 없습니다.", []

    tasks = []
    for review in blog_reviews:
        link = review.get('link')
        if link and 'blog.naver.com' in link:
            tasks.append(scrape_blog_content(link))
        else:
            async def get_empty_result(): return "네이버 블로그가 아니므로 내용을 가져오지 않습니다."
            tasks.append(get_empty_result())

    progress(0.5, desc=f"{len(tasks)}개의 블로그 본문 스크래핑 중...")
    scraped_contents = await asyncio.gather(*tasks)

    scraped_reviews = []
    for i, review in enumerate(blog_reviews):
        review['content'] = scraped_contents[i]
        scraped_reviews.append(review)

    progress(1, desc="완료")

    raw_json_output = json.dumps(scraped_reviews, indent=2, ensure_ascii=False)

    formatted_output_lines = [f"### '{keyword}' 네이버 블로그 검색 및 스크래핑 결과\n"]
    for review in scraped_reviews:
        post_date = review.get('postdate', '')
        if post_date: post_date = f"{post_date[0:4]}-{post_date[4:6]}-{post_date[6:8]}"
        
        title = review.get('title', '제목 없음').replace('[', '\\[').replace(']', '\\]')
        link = review.get('link', '#')
        description = review.get('description', '내용 없음').replace('[', '\\[').replace(']', '\\]')
        content = review.get('content', '본문 없음')

        formatted_output_lines.append(f"**[{title}]({link})** ({post_date})")
        formatted_output_lines.append(f"> {description}...\n")
        formatted_output_lines.append("#### 블로그 본문")
        formatted_output_lines.append(f"```\n{content}\n```\n")

    formatted_output = "\n".join(formatted_output_lines)

    return raw_json_output, formatted_output, scraped_reviews

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
        content = review.get('content', '')
        if "본문 내용을 찾을 수 없습니다" in content or "페이지에 접근하는 중 오류" in content:
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

    - **연계 추천 코스 (주변 즐길거리)**: (행사 전후로 방문하기 좋은 근처 음식점, 카페, 다른 볼거리, 즐길거리 등에 대한 추천)
    - **동선 및 관람 팁**: (방문객의 노하우)
    - **방문객 반응 및 현장 분위기**: (현장의 생생한 분위기)
    - **음식 및 맛집 정보**: (행사장 내부 또는 바로 근처의 식사 정보)
    - **주차 및 교통 팁**: (접근성에 대한 조언)
    - **준비물 및 복장 추천**: (방문 전 준비물 관련)
    - **사진 명소 (포토존)**: (사진 찍기 좋은 곳)
    - **긍정적인 점 (장점)**: (방문객들이 공통적으로 칭찬하는 부분)
    - **아쉬운 점 및 개선사항 (단점)**: (방문객들이 아쉬워하거나 개선을 제안하는 부분)
    - **기타 개인적인 조언**: (위 카테고리에 속하지 않는 유용한 팁)

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