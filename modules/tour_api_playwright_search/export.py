import gradio as gr
import math
import os
import tempfile
import re
import pandas as pd
import xml.etree.ElementTree as ET
from playwright.async_api import expect
import datetime

# Relative imports from within the same module
from . import scraper
from .common import (
    parse_xml_to_ordered_list,
    wait_for_xml_update,
    parse_xml_to_dict_list,
)


async def export_details_to_csv(search_params, progress=gr.Progress(track_tqdm=True)):
    """[최종 리팩토링] 다중 행 데이터 타입(여행 코스, 숙박)을 지원하고 모든 안정성 로직이 포함된 최종 버전입니다."""

    # --- 0. 설정 및 피드백 디렉토리 생성 ---
    ITEMS_PER_PAGE = 12
    all_attraction_details = []

    feedback_dir = os.path.join("Temp", "export_feedback")
    os.makedirs(feedback_dir, exist_ok=True)
    print(f"피드백 스크린샷은 '{feedback_dir}' 폴더에 저장됩니다.")

    def get_screenshot_path(name):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(feedback_dir, f"{timestamp}_{name}.png")

    # CSV 컬럼 순서 유지를 위한 키 리스트
    simple_search_keys, common_info_keys, intro_info_keys, repeat_info_keys = (
        [],
        [],
        [],
        [],
    )
    seen_keys = set()

    def add_key(key, key_list):
        if key and key not in seen_keys:
            seen_keys.add(key)
            key_list.append(key)

    # --- 1. Playwright 초기화 및 초기 검색 ---
    print("CSV 내보내기 프로세스를 시작합니다.")
    initial_params = search_params.copy()
    if initial_params.get("sigungu") == "전체":
        initial_params["sigungu"] = None
    if initial_params.get("cat1") == "선택 안함":
        initial_params["cat1"] = None
    if initial_params.get("cat2") == "선택 안함":
        initial_params["cat2"] = None
    if initial_params.get("cat3") == "선택 안함":
        initial_params["cat3"] = None

    p, browser, page = await scraper.get_page_context()

    try:
        print("초기 검색을 시작합니다...")
        progress(0, desc="전체 아이템 수를 확인하는 중...")
        total_count = await scraper.perform_initial_search_for_export(
            page, **initial_params
        )

        if total_count == 0:
            gr.Info("내보낼 데이터가 없습니다.")
            print("내보낼 데이터가 없어 프로세스를 종료합니다.")
            return None

        total_pages = math.ceil(total_count / ITEMS_PER_PAGE)
        print(
            f"초기 검색 완료. 총 {total_count}개의 아이템, {total_pages}개의 페이지를 확인했습니다."
        )
        await page.screenshot(path=get_screenshot_path("01_initial_search_results.png"))

        # --- 2. 페이지 순회 (Outer Loop) ---
        for page_num in progress.tqdm(range(1, total_pages + 1), desc="페이지 처리 중"):
            print(f"\n--- {page_num} 페이지 처리를 시작합니다. ---")
            await scraper.go_to_page(page, page_num, total_pages)

            if page_num > 1:
                print(
                    f"    페이지 안정화를 위해 새로고침, 재검색, 페이지 재이동을 수행합니다..."
                )
                await page.reload(wait_until="networkidle")
                await scraper.perform_initial_search_for_export(page, **initial_params)
                await scraper.go_to_page(page, page_num, total_pages)
                print(f"    안정화 완료.")

            await expect(page.locator("ul.gallery-list")).to_be_visible(timeout=15000)
            print(f"{page_num} 페이지로 이동 완료.")

            items_on_this_page_data = await scraper.get_items_from_page(
                page, page_num, total_pages
            )
            item_count_on_page = len(items_on_this_page_data)
            print(
                f"{page_num} 페이지에서 {item_count_on_page}개의 아이템을 확인했습니다."
            )

            # --- 3. 페이지 내 아이템 순회 (Inner Loop) ---
            for i in range(item_count_on_page):
                content_id = items_on_this_page_data[i].get("contentid")
                if not content_id:
                    print(
                        f"  [{i+1}/{item_count_on_page}] 콘텐츠 ID를 찾을 수 없어 건너뜁니다."
                    )
                    continue

                print(
                    f"  [{i+1}/{item_count_on_page}] 콘텐츠 ID '{content_id}' 처리를 시작합니다."
                )

                try:
                    # --- 4. 아이템 클릭 및 모든 탭 XML 수집 ---
                    current_item_locator = page.locator("ul.gallery-list > li > a").nth(
                        i
                    )
                    await expect(current_item_locator).to_be_visible(timeout=10000)
                    await current_item_locator.click()

                    xml_textarea_locator = page.locator("textarea#ResponseXML")
                    await expect(xml_textarea_locator).to_have_value(
                        re.compile(f"<contentid>{content_id}</contentid>"),
                        timeout=30000,
                    )
                    await expect(
                        page.locator('button:has-text("공통정보")')
                    ).to_be_visible(timeout=10000)
                    print("    상세 정보 UI 로딩 완료.")

                    xml_sources = {}
                    base_info_from_list = next(
                        (
                            item
                            for item in items_on_this_page_data
                            if item["contentid"] == content_id
                        ),
                        {},
                    )
                    content_type_id = base_info_from_list.get("contenttypeid")

                    tabs_to_process = ["공통정보", "소개정보"]
                    if content_type_id == "25":
                        tabs_to_process.append("코스정보")
                    elif content_type_id == "32":
                        tabs_to_process.append("객실정보")
                    else:
                        tabs_to_process.append("반복정보")

                    for tab_name in tabs_to_process:
                        try:
                            if tab_name == "공통정보":
                                print(f"    - {tab_name} 수집 중...")
                                new_xml = await xml_textarea_locator.input_value()
                                if "<title>" not in new_xml:
                                    raise ValueError(
                                        "공통정보 XML에 title 태그가 없습니다."
                                    )
                                xml_sources[tab_name] = new_xml
                                continue

                            print(f"    - {tab_name} 탭 확인 중...")
                            tab_locator = page.locator(f'button:has-text("{tab_name}")')
                            if not await tab_locator.is_visible(timeout=5000):
                                print(
                                    f"    - '{tab_name}' 탭이 존재하지 않아 건너뜁니다."
                                )
                                continue

                            print(f"    - {tab_name} 탭으로 이동 및 정보 수집 중...")
                            initial_xml = await xml_textarea_locator.input_value()
                            await tab_locator.click()
                            await wait_for_xml_update(page, initial_xml)
                            new_xml = await xml_textarea_locator.input_value()

                            # 데이터 유효성 검증
                            if tab_name == "소개정보":
                                key_tags = {
                                    "15": "<eventstartdate>",
                                    "28": "<infocenterleports>",
                                    "14": "<infocenterculture>",
                                    "12": "<infocenter>",
                                    "32": "<checkintime>",
                                    "25": "<distance>",
                                    "38": "<infocentershopping>",
                                    "39": "<firstmenu>",
                                }
                                standard_tag = key_tags.get(content_type_id, "<item>")
                                if standard_tag not in new_xml:
                                    raise ValueError(
                                        f"소개정보 XML 유효성 검증 실패 (기준 태그: {standard_tag})"
                                    )
                            elif tab_name == "반복정보":
                                if "<totalCount>0</totalCount>" not in new_xml and (
                                    "<infoname>" not in new_xml
                                    and "<infotext>" not in new_xml
                                ):
                                    raise ValueError(
                                        "반복정보 XML에 infoname과 infotext 태그가 모두 없어 재시도합니다."
                                    )

                            xml_sources[tab_name] = new_xml
                        except Exception as e:
                            print(
                                f"    - '{tab_name}' 탭 처리 실패. 1초 후 재시도합니다... 오류: {e}"
                            )
                            await page.wait_for_timeout(1000)
                            try:
                                if tab_name == "공통정보":
                                    new_xml = await xml_textarea_locator.input_value()
                                    if "<title>" not in new_xml:
                                        raise ValueError("재시도 실패: title 태그 없음")
                                else:
                                    initial_xml = (
                                        await xml_textarea_locator.input_value()
                                    )
                                    await tab_locator.click()
                                    await wait_for_xml_update(page, initial_xml)
                                    new_xml = await xml_textarea_locator.input_value()
                                xml_sources[tab_name] = new_xml
                                print(f"    - '{tab_name}' 탭 재시도 성공.")
                            except Exception as e2:
                                print(
                                    f"    - '{tab_name}' 탭 재시도 실패. 건너뜁니다. 오류: {e2}"
                                )

                    # --- 4b. 상태 초기화 ---
                    common_info_tab_locator = page.locator(
                        'button:has-text("공통정보")'
                    )
                    if await common_info_tab_locator.is_visible(timeout=5000):
                        parent_li = common_info_tab_locator.locator("xpath=..")
                        if "on" not in (await parent_li.get_attribute("class") or ""):
                            initial_xml = await xml_textarea_locator.input_value()
                            await common_info_tab_locator.click()
                            await wait_for_xml_update(page, initial_xml)

                    # --- 5. 수집된 XML 파싱 및 행 생성 ---
                    base_details = {}
                    # 목록에서 가져온 초기 정보 추가
                    initial_item_data = next(
                        (
                            item
                            for item in items_on_this_page_data
                            if item["contentid"] == content_id
                        ),
                        None,
                    )
                    if initial_item_data and "initial_item_xml" in initial_item_data:
                        root = ET.fromstring(
                            f"<root>{initial_item_data['initial_item_xml']}</root>"
                        )
                        simple_item_element = root.find("item")
                        if simple_item_element is not None:
                            for child in simple_item_element:
                                if child.text and child.text.strip():
                                    add_key(child.tag, simple_search_keys)
                                    base_details[child.tag] = child.text.strip()

                    # 공통정보, 소개정보 파싱하여 base_details에 추가
                    for tab_name in ["공통정보", "소개정보"]:
                        item_details_list = parse_xml_to_ordered_list(
                            xml_sources.get(tab_name, "")
                        )
                        for key, value in item_details_list:
                            original_key = key
                            counter = 1
                            while key in base_details:
                                counter += 1
                                key = f"{original_key}_{counter}"
                            add_key(
                                key,
                                (
                                    common_info_keys
                                    if tab_name == "공통정보"
                                    else intro_info_keys
                                ),
                            )
                            base_details[key] = value

                    # contenttypeid에 따라 분기 처리
                    if content_type_id == "25" or content_type_id == "32":
                        multi_row_tab_name = (
                            "코스정보" if content_type_id == "25" else "객실정보"
                        )
                        sub_items = parse_xml_to_dict_list(
                            xml_sources.get(multi_row_tab_name, "")
                        )
                        if sub_items:
                            for sub_item in sub_items:
                                new_row = base_details.copy()
                                new_row.update(sub_item)
                                all_attraction_details.append(new_row)
                                for key in sub_item.keys():
                                    add_key(key, repeat_info_keys)
                        else:
                            all_attraction_details.append(base_details)
                    else:
                        item_details_list = parse_xml_to_ordered_list(
                            xml_sources.get("반복정보", "")
                        )
                        for key, value in item_details_list:
                            original_key = key
                            counter = 1
                            while key in base_details:
                                counter += 1
                                key = f"{original_key}_{counter}"
                            add_key(key, repeat_info_keys)
                            base_details[key] = value
                        all_attraction_details.append(base_details)

                    print("    XML 파싱 및 데이터 저장 완료.")

                    # --- 6. 목록으로 돌아가기 ---
                    await page.go_back()
                    await page.wait_for_load_state("networkidle")

                except Exception as e:
                    error_message = f"콘텐츠 ID '{content_id}' 처리 중 오류 발생: {e}. 복구를 시도하고 다음 항목으로 넘어갑니다."
                    print(error_message)
                    await page.screenshot(
                        path=get_screenshot_path(f"{page_num}_{i+1}_error.png")
                    )

                    # [요청 수정] 아이템을 건너뛰는 것이 확정된 이 시점에 바로 로그를 기록
                    try:
                        log_file_path = "unrecoverable_error_log.txt"
                        log_content = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [복구 후 건너뜀] {page_num} 페이지의 {i + 1} 번째 관광 데이터(콘텐츠 ID: {content_id})를 건너뛰었습니다. 최초 오류: {e}\n"
                        with open(log_file_path, "a", encoding="utf-8") as f:
                            f.write(log_content)
                    except Exception as log_e:
                        print(f"    - 파일 로그 작성에 실패했습니다: {log_e}")

                    # 다음 아이템을 위해 복구 시도
                    try:
                        print(
                            f"복구를 시도합니다. {page_num} 페이지의 처음부터 다시 로드합니다."
                        )
                        await page.goto(scraper.BASE_URL, wait_until="load")
                        await page.wait_for_load_state("domcontentloaded")
                        await scraper.perform_initial_search_for_export(
                            page, **initial_params
                        )
                        await scraper.go_to_page(page, page_num, total_pages)
                        print("페이지 재로드 및 복구 완료. 다음 아이템으로 진행합니다.")
                    except Exception as recovery_e:
                        print(
                            f"치명적인 복구 오류 발생: {recovery_e}. 이 아이템을 건너뛰고 계속합니다."
                        )
                        # 복구 자체도 실패하면 추가 로그 기록
                        try:
                            log_file_path = "unrecoverable_error_log.txt"
                            log_content = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [복구 실패] {page_num} 페이지의 {i + 1} 번째 관광 데이터(콘텐츠 ID: {content_id})의 복구에 실패했습니다. 오류: {recovery_e}\n"
                            with open(log_file_path, "a", encoding="utf-8") as f:
                                f.write(log_content)
                        except Exception as log_e:
                            print(f"    - 파일 로그 작성에 실패했습니다: {log_e}")
                    continue

    finally:
        print("\n모든 페이지 처리를 완료했습니다. 브라우저를 닫습니다.")
        await scraper.close_page_context(p, browser)

    # --- 7. CSV 파일 생성 ---
    if not all_attraction_details:
        gr.Info("수집된 상세 정보가 없습니다.")
        print("수집된 정보가 없어 CSV 파일을 생성하지 않습니다.")
        return None

    print("수집된 데이터를 CSV 파일로 변환합니다...")
    progress(0.9, desc="CSV 파일 생성 중...")
    final_ordered_columns = (
        simple_search_keys + common_info_keys + intro_info_keys + repeat_info_keys
    )
    df = pd.DataFrame(all_attraction_details)
    existing_cols = [col for col in final_ordered_columns if col in df.columns]
    df = df.reindex(columns=existing_cols).fillna("")

    if "homepage" in df.columns:
        df["homepage"] = df["homepage"].apply(
            lambda x: (
                re.search(r'href=["\\](.*?)["\\]', str(x)).group(1)
                if x and isinstance(x, str) and re.search(r'href=["\\](.*?)["\\]', x)
                else x
            )
        )

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            mode="w",
            suffix=".csv",
            prefix="tour_details_all_",
            encoding="utf-8-sig",
        ) as temp_f:
            df.to_csv(temp_f.name, index=False)
            gr.Info("모든 항목에 대한 CSV 파일이 성공적으로 생성되었습니다.")
            print(f"CSV 파일이 성공적으로 생성되었습니다: {temp_f.name}")
            return temp_f.name
    except Exception as e:
        gr.Error(f"CSV 파일 저장 오류: {e}")
        print(f"CSV 파일 저장 중 오류 발생: {e}")
        return None
