import gradio as gr

from .search import search_naver_reviews_and_scrape, summarize_blog_contents_stream, answer_question_from_reviews_stream

def create_naver_search_tab():
    """'네이버 검색 (임시)' 탭의 UI를 생성합니다."""
    with gr.Blocks() as tab:
        gr.Markdown("### 네이버 블로그 후기 검색 및 요약")
        
        # --- 상태 변수 ---
        search_results_state = gr.State([])

        # --- UI 컴포넌트 ---
        with gr.Row():
            keyword_input = gr.Textbox(
                label="검색할 행사 키워드를 입력하세요",
                placeholder="예: 2025 한강 불빛 공연",
                lines=1,
                scale=3
            )
            search_button = gr.Button("검색 실행", variant="primary", scale=1)
            summarize_button = gr.Button("결과 요약하기", scale=1)

        gr.Markdown("--- ")
        summary_output = gr.Markdown(label="방문객 경험 중심 요약 (GPT-4.1-mini)")
        image_gallery = gr.Gallery(label="블로그 이미지 모아보기", columns=6, height="auto")
        
        gr.Markdown("---")
        gr.Markdown("### 💬 후기 기반 챗봇")
        gr.Markdown("블로그 후기 내용을 바탕으로 궁금한 점을 질문해보세요. (예: 주차 정보, 유모차 끌기 편한가요?, 비 오는 날 가도 괜찮나요?)")
        
        with gr.Row():
            question_input = gr.Textbox(label="질문 입력", placeholder="질문을 입력하세요...", scale=4)
            ask_button = gr.Button("질문하기", scale=1)
        
        answer_output = gr.Markdown(label="챗봇 답변")

        gr.Markdown("---")
        with gr.Row():
            raw_json_output = gr.Textbox(
                label="Raw JSON 결과", 
                lines=20, 
                interactive=False
            )
            formatted_output = gr.Markdown()
            
        # --- 이벤트 핸들러 ---
        search_button.click(
            fn=search_naver_reviews_and_scrape,
            inputs=[keyword_input],
            outputs=[raw_json_output, formatted_output, search_results_state, image_gallery]
        )

        summarize_button.click(
            fn=summarize_blog_contents_stream,
            inputs=[search_results_state],
            outputs=[summary_output]
        )

        ask_button.click(
            fn=answer_question_from_reviews_stream,
            inputs=[question_input, search_results_state],
            outputs=[answer_output]
        )
    return tab
