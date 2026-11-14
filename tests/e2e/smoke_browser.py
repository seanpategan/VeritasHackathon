"""Browser smoke test (Playwright, Python). Requires a running server and network access.

Usage:  python tests/e2e/smoke_browser.py [BASE_URL] [OUT_DIR]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
    errors = []
    for name, vp in [("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})]:
        page = browser.new_page(viewport=vp)
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(BASE + "/")
        page.wait_for_selector("#dataset-label strong", timeout=30000, state="attached")
        page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / f"{name}-1-overview.png"))
        # search
        page.fill("#search-input", "Ames, IA")
        page.wait_for_selector("#search-results li[role=option]", timeout=10000)
        page.screenshot(path=str(OUT / f"{name}-2-search.png"))
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        # bookmark -> auto-select
        page.select_option("#bookmark-select", "story-ia")
        page.wait_for_selector(".card", timeout=45000)
        page.wait_for_timeout(5000)
        page.screenshot(path=str(OUT / f"{name}-3-selected.png"))
        page.locator(".card").first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / f"{name}-4-cards.png"))
        text = page.inner_text("#panel")
        assert "Mapped crop coverage—not a property boundary." in text
        assert "Current planting and field conditions are not verified." in text
        assert "Corn" in text and "2025" in text
        print(name, "OK; cards:", page.locator(".card").count())
        page.close()
    browser.close()
    print("console errors:", errors)
