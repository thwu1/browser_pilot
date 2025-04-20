from playwright.sync_api import sync_playwright

def test_playwright_install():

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("https://www.example.com")
        page.accessibility.snapshot()
        browser.new_context()
        page.close()
        browser.close()