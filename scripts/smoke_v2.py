"""Verify the isolated /v2 UI and preservation of the committed root UI."""

import argparse
import hashlib
import subprocess
from pathlib import Path

import requests
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ROOT_UI_COMMIT = "4d454c7"
ROOT_UI_FILES = (
    "webapp/templates/index.html",
    "webapp/static/style.css",
    "webapp/static/script.js",
)


def verify_root_files(base_url: str) -> None:
    for relative_path in ROOT_UI_FILES:
        committed = subprocess.check_output(
            ["git", "show", f"{ROOT_UI_COMMIT}:{relative_path}"], cwd=ROOT
        )
        current = (ROOT / relative_path).read_bytes()
        # Git normalizes CRLF in text working trees; compare canonical Git bytes.
        canonical_current = current.replace(b"\r\n", b"\n")
        assert hashlib.sha256(canonical_current).digest() == hashlib.sha256(committed).digest(), relative_path
        route = "/" if relative_path.endswith("index.html") else relative_path.removeprefix("webapp")
        response = requests.get(f"{base_url}{route}", timeout=10)
        response.raise_for_status()
        assert response.content == current, f"Served root asset differs: {route}"


def assert_no_overflow(page) -> None:
    dimensions = page.evaluate(
        "({content: document.documentElement.scrollWidth, viewport: innerWidth})"
    )
    assert dimensions["content"] <= dimensions["viewport"], dimensions


def select_page(page, name: str) -> None:
    page.locator(f'.nav-item[data-page="{name}"]:visible').first.click()
    expect(page.locator(f"#page-{name}")).to_be_visible()
    assert_no_overflow(page)


def assert_history_cards(page, *, multiple_columns: bool) -> None:
    """Check usable image cards and their flow without fixing exact grid tracks."""
    cards = page.locator("#historyList .hist-item")
    expect(cards).to_have_count(3)
    bounds = []
    for card in cards.all():
        expect(card.locator(".hist-food")).not_to_be_empty()
        expect(card.locator(".hist-sub")).not_to_be_empty()
        expect(card.locator(".hist-del")).to_have_accessible_name("Delete entry")
        photo = card.locator("img.hist-thumb")
        expect(photo).to_be_visible()
        assert photo.evaluate("image => image.complete && image.naturalWidth > 0")
        card_bounds = card.bounding_box()
        image_bounds = photo.bounding_box()
        assert card_bounds and image_bounds
        assert image_bounds["width"] > card_bounds["width"] / 2, "History thumbnail is still a list icon"
        assert image_bounds["height"] > 80, "History card image is too small to inspect"
        assert image_bounds["y"] < card.locator(".hist-food").bounding_box()["y"], "History image should lead the card"
        bounds.append(card_bounds)
    if multiple_columns:
        assert any(
            abs(first["y"] - second["y"]) < 2 and abs(first["x"] - second["x"]) > 20
            for index, first in enumerate(bounds)
            for second in bounds[index + 1:]
        ), "Desktop history should lay out cards in multiple columns"
    else:
        assert all(bounds[index]["y"] < bounds[index + 1]["y"] for index in range(len(bounds) - 1)), "Phone history should stack cards in reading order"
    assert_no_overflow(page)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    verify_root_files(base_url)
    for route in ("/v2", "/v2/"):
        response = requests.get(f"{base_url}{route}", timeout=10, allow_redirects=False)
        assert response.status_code == 200, (route, response.status_code)
    health = requests.get(f"{base_url}/api/health", timeout=10)
    health.raise_for_status()
    assert health.json()["model_ready"] is True

    screenshots = ROOT / ".impeccable" / "review"
    screenshots.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
        context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
        page = context.new_page()
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: errors.append(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        page.goto(f"{base_url}/v2", wait_until="networkidle")
        expect(page.locator("#page-scan")).to_be_visible()
        expect(page.locator("#uploadZone")).to_be_visible()
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.fonts.check('400 16px \"Mona Sans Expanded\"')"), "Mona font unavailable"
        font_faces = page.evaluate("[...document.fonts].filter(font => font.status === 'loaded').map(font => font.family)")
        assert any("Mona" in family for family in font_faces), font_faces
        assert_no_overflow(page)
        page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)

        select_page(page, "profile")
        page.locator('input[name="allergy"][value="nuts"]').check()
        page.locator("#btnSaveProfile").click()
        expect(page.locator("#profileStatus")).to_contain_text("saved")
        page.reload(wait_until="networkidle")
        select_page(page, "profile")
        expect(page.locator('input[name="allergy"][value="nuts"]')).to_be_checked()
        select_page(page, "scan")
        page.locator("#btnViva").click()
        expect(page.locator("#vivaPanel")).to_be_visible()
        expect(page.locator("#factParameters")).to_contain_text("M")
        expect(page.locator("#vivaReady")).to_contain_text("ready")
        page.locator("#btnViva").click()
        expect(page.locator("#vivaPanel")).to_be_hidden()

        page.evaluate("""() => {
            Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {
                getUserMedia: async () => { throw new DOMException('Denied for smoke test', 'NotAllowedError'); }
            }});
        }""")
        page.locator("#btnCamera").click()
        expect(page.locator("#cameraModal")).to_be_visible()
        expect(page.locator("#btnCameraFallback")).to_be_visible()
        expect(page.locator("#cameraMsg")).to_contain_text("permission was denied")
        expect(page.locator("#btnSnap")).to_be_hidden()
        page.locator("#btnCamClose").click()
        expect(page.locator("#cameraModal")).to_be_hidden()

        page.locator("#galleryInput").set_input_files(str(ROOT / "test_pizza_realistic.png"))
        expect(page.locator("#previewCard")).to_be_visible()
        page.locator("#btnScan").click()
        expect(page.locator("#results")).to_be_visible(timeout=60_000)
        expect(page.locator("#topPredictions .pred-row")).to_have_count(3)
        expect(page.locator("#confidenceBadge")).to_contain_text("%")
        expect(page.locator("#ingredientsCard")).to_be_visible()
        expect(page.locator("#ingredientsList")).not_to_be_empty()
        expect(page.locator("#guardrailResult")).to_contain_text("Possible allergy concern")
        assert_no_overflow(page)
        page.locator("#btnFeedbackWrong").click()
        expect(page.locator("#feedbackForm")).to_be_visible()
        assert "google.com/maps/search" in page.locator("#findNearby").get_attribute("href")
        page.locator("#btnGradcam").click()
        expect(page.locator("#gradcamResult")).to_be_visible(timeout=60_000)
        assert page.locator("#gradcamImage").get_attribute("src").startswith("data:image/jpeg;base64,")
        page.locator("#btnCompareTta").click()
        expect(page.locator("#ttaComparison")).to_be_visible(timeout=60_000)
        expect(page.locator("#ttaComparison")).to_contain_text("3-view TTA")
        with page.expect_download() as download_event:
            page.locator("#btnDownloadReport").click()
        assert download_event.value.failure() is None
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshots / "warning-results.png"), full_page=True)

        select_page(page, "history")
        expect(page.locator("#historyList .hist-item")).to_have_count(1)
        thumbnail = page.locator("#historyList .hist-thumb").first
        assert thumbnail.get_attribute("src").startswith("data:image/jpeg;base64,")
        page.reload(wait_until="networkidle")
        select_page(page, "history")
        expect(page.locator("#historyList .hist-item")).to_have_count(1)
        assert page.locator("#historyList img").first.get_attribute("src").startswith("data:image/jpeg;base64,")

        # Reuse the real scan as explicit browser-only layout fixtures. This does
        # not create server records or require additional model predictions.
        history_fixture = page.evaluate("""() => {
            const first = JSON.parse(localStorage.getItem('foodlens.history'))[0];
            return [0, 1, 2].map(index => ({...first, id: first.id + index, ts: first.ts - index * 60000}));
        }""")
        page.evaluate("entries => localStorage.setItem('foodlens.history', JSON.stringify(entries))", history_fixture)
        page.reload(wait_until="networkidle")
        select_page(page, "history")
        assert_history_cards(page, multiple_columns=True)
        page.screenshot(path=str(screenshots / "history-desktop.png"), full_page=True)
        page.locator("#historyList .hist-del").first.click()
        expect(page.locator("#historyList .hist-item")).to_have_count(2)
        page.reload(wait_until="networkidle")
        select_page(page, "history")
        expect(page.locator("#historyList .hist-item")).to_have_count(2)
        select_page(page, "evaluation")
        expect(page.locator("#evaluationMetrics")).to_contain_text("88.21%")
        expect(page.locator("#ttaTable tbody tr")).not_to_have_count(0)
        expect(page.locator("#calibrationCard")).to_contain_text("development images")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshots / "evaluation.png"), full_page=True)
        select_page(page, "about")
        page.locator("#themeToggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshots / "dark.png"), full_page=True)
        page.locator("#themeToggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
        mobile = mobile_context.new_page()
        mobile.on("pageerror", lambda error: errors.append(str(error)))
        mobile.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        mobile.goto(f"{base_url}/v2/", wait_until="networkidle")
        mobile.evaluate("document.fonts.ready")
        expect(mobile.locator("#uploadZone")).to_be_visible()
        assert_no_overflow(mobile)
        mobile.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
        mobile.locator("#btnMenu").click()
        expect(mobile.locator("#drawer")).to_be_visible()
        select_page(mobile, "profile")
        expect(mobile.locator("#drawer")).to_be_hidden()
        mobile.evaluate("entries => localStorage.setItem('foodlens.history', JSON.stringify(entries))", history_fixture)
        mobile.reload(wait_until="networkidle")
        mobile.locator("#btnMenu").click()
        select_page(mobile, "history")
        assert_history_cards(mobile, multiple_columns=False)
        mobile.screenshot(path=str(screenshots / "history-mobile.png"), full_page=True)
        mobile_context.close()
        context.close()
        browser.close()

    assert not errors, "Browser errors:\n" + "\n".join(errors)
    verify_root_files(base_url)
    print("PASS: root UI preserved; v2 fonts, desktop/mobile, profile, live inference, model tools, history and evaluation")
    print(f"Screenshots: {screenshots}")


if __name__ == "__main__":
    main()
