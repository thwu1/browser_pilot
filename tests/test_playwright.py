from playwright.sync_api import sync_playwright
import time

def test_playwright():

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # context = browser.new_context()
        # page = context.new_page()

        time.sleep(1)
        print(browser.contexts)
        # print(browser.context_count)
        # context = browser.contexts[0]
        page = browser.new_page()
        print(browser.contexts)
        page.goto("https://www.example.com")
        print(f"Page title: {page.title()}")
        print(page.accessibility.snapshot())
        page.goto("https://www.youtube.com")
        print(f"Page title: {page.title()}")
        print(page.accessibility.snapshot())
        page.goto("https://www.netflix.com")
        print(f"Page title: {page.title()}")
        print(page.accessibility.snapshot())
        # page.goto("https://www.example.com")
        browser.new_context()
        print(browser.contexts)
        print(f"Page title: {page.title()}")
        
        page.close()
        browser.close()