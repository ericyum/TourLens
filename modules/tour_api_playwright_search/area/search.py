import asyncio
from playwright.async_api import Page
from modules.tour_api_playwright_search.common import get_page_context, close_page_context, BASE_URL
from utils import get_api_items

# This file now contains only the self-contained functions for getting dropdown options,
# styled after the working reference project 'c'.

async def get_sigungu_options(province):
    if not province or province == "전국": return []
    p, browser, page = await get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("지역 선택")').click()
        await page.wait_for_selector('div.modal.region-modal.on', timeout=5000)
        await page.locator(f'div.modal.region-modal.on a[name="areaCd"]:has-text("{province}")').click()
        await page.wait_for_timeout(1000) # crucial wait
        sigungu_names = await page.locator('div.modal.region-modal.on a[name="signguCd"]').all_text_contents()
        return [name.strip() for name in sigungu_names if name.strip()]
    finally:
        await close_page_context(p, browser)

async def get_large_category_options(tourism_type):
    if not tourism_type or tourism_type == "선택 안함": return []
    p, browser, page = await get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        await page.locator('button:has-text("관광타입 선택")').click()
        await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
        await page.locator('div.modal#popup4.on a:has-text("확인")').click()
        await page.locator('div.overlay.on').wait_for(state='hidden')
        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        category_names = await page.locator('div.modal#popup1.on a[name="cat1"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await close_page_context(p, browser)

async def get_medium_category_options(tourism_type, large_category):
    if not large_category or large_category == "선택 안함":
        return []
    p, browser, page = await get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)
        
        if tourism_type and tourism_type != "선택 안함":
            await page.locator('button:has-text("관광타입 선택")').click()
            await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
            await page.locator('div.modal#popup4.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')

        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{large_category}")').click()
        await page.wait_for_timeout(500) # crucial wait
        category_names = await page.locator('div.modal#popup1.on a[name="cat2"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await close_page_context(p, browser)

async def get_small_category_options(tourism_type, large_category, medium_category):
    if not large_category or large_category == "선택 안함" or not medium_category or medium_category == "선택 안함":
        return []
    p, browser, page = await get_page_context()
    try:
        await page.goto(BASE_URL, timeout=90000)

        if tourism_type and tourism_type != "선택 안함":
            await page.locator('button:has-text("관광타입 선택")').click()
            await page.locator(f'div.modal#popup4.on a:has-text("{tourism_type}")').click()
            await page.locator('div.modal#popup4.on a:has-text("확인")').click()
            await page.locator('div.overlay.on').wait_for(state='hidden')

        await page.locator('button:has-text("서비스 분류 선택")').click()
        await page.wait_for_selector('div.modal#popup1.on')
        await page.locator(f'div.modal#popup1.on a[name="cat1"]:has-text("{large_category}")').click()
        await page.wait_for_timeout(500) # crucial wait
        await page.locator(f'div.modal#popup1.on a[name="cat2"]:has-text("{medium_category}")').click()
        await page.wait_for_timeout(500) # crucial wait
        category_names = await page.locator('div.modal#popup1.on a[name="cat3"]').all_text_contents()
        return [name.strip() for name in category_names if name.strip()]
    finally:
        await close_page_context(p, browser)
