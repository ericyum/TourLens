import asyncio
from playwright.async_api import Page

async def navigate_to_location_search_page(page: Page, **kwargs):
    print("[LOC_LOG] Starting navigation for location-based search.")
    # Switch to the correct main tab
    print("[LOC_LOG] Waiting for location tab button to be visible...")
    await page.locator('button#P2[name="/useInforLocation"]:visible').click()
    print("[LOC_LOG] Clicked location tab button.")
    await page.screenshot(path="debug_location_nav_1_after_tab_click.png") # 스크린샷 추가
    
    print("[LOC_LOG] Waiting for network to be idle after tab switch...")
    await page.wait_for_load_state('networkidle') # 탭 전환 후 네트워크 안정화 대기
    print("[LOC_LOG] Network is idle.")
    await page.screenshot(path="debug_location_nav_2_after_networkidle.png") # 스크린샷 추가
    
    # input#searchXCoord가 DOM에 붙을 때까지 기다립니다. (visible 상태는 아닐 수 있음)
    print("[LOC_LOG] Waiting for searchXCoord input to be attached...")
    await page.wait_for_selector('input#searchXCoord', state='attached', timeout=10000) 
    print("[LOC_LOG] searchXCoord input is attached.")
    await page.screenshot(path="debug_location_nav_3_after_xcoord_attached.png") # 스크린샷 추가

    # mapX와 mapY는 자동으로 입력되지 않으므로 fill 로직 다시 추가
    map_x = kwargs.get("map_x", "")
    map_y = kwargs.get("map_y", "")
    radius = kwargs.get("radius", "2000")
    print(f"[LOC_LOG] Filling coordinates and radius: map_x={map_x}, map_y={map_y}, radius={radius}")
    await page.locator('input#searchXCoord').fill(map_x)
    print("[LOC_LOG] Filled map_x.")
    await page.locator('input#searchYCoord').fill(map_y)
    print("[LOC_LOG] Filled map_y.")
    await page.screenshot(path="debug_location_nav_4_after_xy_fill.png") # 스크린샷 추가

    # 거리 필드는 사용자가 설정하는 대로 변경하므로 fill 로직 유지
    await page.locator('input#searchRadius').fill(radius)
    print("[LOC_LOG] Filled radius.")
    await page.screenshot(path="debug_location_nav_5_after_radius_fill.png") # 스크린샷 추가
    
    # Handle tourism type if provided for location search
    tourism_type = kwargs.get("tourism_type")
    print(f"[LOC_LOG] Tourism type selected: {tourism_type}")
    if tourism_type and tourism_type != "선택 안함":
        # Use a more specific selector to find the button within its list item
        tourism_type_button_locator = page.locator('button:has-text("관광타입 선택")')
        
        # 버튼이 visible 상태가 될 때까지 기다립니다.
        print("[LOC_LOG] Waiting for tourism type button to be visible...")
        await tourism_type_button_locator.wait_for(state='visible', timeout=30000)
        print("[LOC_LOG] Tourism type button is visible.")
        await page.screenshot(path="debug_location_nav_6_after_tourism_type_button_visible.png") # 스크린샷 추가
        
        # Playwright는 visible 상태이면 자동으로 enabled 상태도 확인합니다.
        print("[LOC_LOG] Clicking tourism type button...")
        await tourism_type_button_locator.click() # force=True 제거
        print("[LOC_LOG] Clicked tourism type button.")
        await page.screenshot(path="debug_location_nav_7_after_tourism_type_button_click.png") # 스크린샷 추가
        
        # 모달 창 자체가 visible 상태가 될 때까지 기다립니다.
        print("[LOC_LOG] Waiting for tourism type modal to be visible...")
        await page.locator('div.modal#popup4.on').wait_for(state='visible', timeout=60000) # 타임아웃 증가
        print("[LOC_LOG] Tourism type modal is visible.")
        await page.screenshot(path="debug_location_nav_8_after_modal_visible.png") # 스크린샷 추가

        selected_type_locator = page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")')
        print(f"[LOC_LOG] Waiting for '{tourism_type}' option to be visible in modal...")
        await selected_type_locator.wait_for(state='visible', timeout=60000) # 타임아웃 증가
        print(f"[LOC_LOG] '{tourism_type}' option is visible.")
        await page.screenshot(path="debug_location_nav_9_before_selected_type_click.png") # 스크린샷 추가
        
        print(f"[LOC_LOG] Clicking '{tourism_type}' option...")
        await selected_type_locator.click()
        print(f"[LOC_LOG] Clicked '{tourism_type}' option.")
        await page.screenshot(path="debug_location_nav_10_after_selected_type_click.png") # 스크린샷 추가
        
        print("[LOC_LOG] Clicking '확인' (Confirm) button in modal...")
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        print("[LOC_LOG] Clicked '확인' (Confirm) button.")
        await page.screenshot(path="debug_location_nav_11_after_confirm_click.png") # 스크린샷 추가
        
        print("[LOC_LOG] Waiting for overlay to be hidden...")
        await page.locator('div.overlay.on').wait_for(state='hidden')
        print("[LOC_LOG] Overlay is hidden.")
        await page.screenshot(path="debug_location_nav_12_after_overlay_hidden.png") # 스크린샷 추가
    
    print("[LOC_LOG] Finished navigation for location-based search.")