"""Playwright e2e tests for the generated obs static SPA.

Drives headless chromium against a real served bundle (see conftest `site`). Asserts the
two-route SPA behaves: overview scatter renders, a mark click deep-links into the run
Gantt (URL + view), the theme toggle flips the canvas theme, deep links open detail
directly, the Back button restores the overview, and the sidebar collapses.

Requires browsers: `playwright install chromium` (the `make test-e2e` target does this).
Needs network — the page loads Plotly/Tailwind/Poppins from their CDNs.
"""

# Standard Library
import re

# Third Party
import pytest
from playwright.sync_api import Page, expect

POINT = "#scatter g.points path.point"
COLLAPSED = re.compile(r"\bsidebar-collapsed\b")


def _click_first_point(page: Page) -> None:
    """Click a scatter mark by its PIXEL centre.

    Plotly overlays a transparent drag layer (`rect.nsewdrag`) on the points for pan/zoom,
    so a DOM click on the <path> is both intercepted and bypasses Plotly's own hit-detection.
    A real mouse click at the point's coordinates lands on the drag layer, where Plotly
    resolves the nearest point and fires `plotly_click`.
    """
    box = page.locator(POINT).first.bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


@pytest.fixture
def overview(page: Page, site):
    """Open the overview and wait for the Plotly scatter to paint."""
    page.goto(site.url, wait_until="networkidle")
    page.wait_for_selector(POINT, timeout=20_000)
    return page


def test_overview_renders_scatter(overview):
    expect(overview.locator("body")).to_have_attribute("data-view", "overview")
    # Three seeded runs ⇒ three scatter points across the two (pass/fail) traces.
    assert overview.locator(POINT).count() == 3
    expect(overview.locator("#status")).to_contain_text("runs")
    expect(overview.locator("#overview-stats")).to_contain_text("failed  1")


def test_click_mark_opens_run_detail(overview):
    _click_first_point(overview)
    overview.wait_for_function("() => new URLSearchParams(location.search).has('run')", timeout=10_000)
    expect(overview.locator("body")).to_have_attribute("data-view", "detail")
    # The detail Gantt is an inline SVG with one lane <rect> per thread.
    expect(overview.locator("#chart svg")).to_be_visible()
    expect(overview.locator("#status")).to_contain_text("nodes")


def test_theme_toggle_flips_data_theme(overview):
    before = overview.locator("html").get_attribute("data-theme")
    overview.locator("#btn-theme").click()
    after = overview.locator("html").get_attribute("data-theme")
    assert {before, after} == {"light", "dark"}
    # Toggling persists for the next load.
    assert overview.evaluate("() => localStorage.getItem('obs-theme')") == after


def test_deep_link_opens_detail_directly(page: Page, site):
    page.goto(f"{site.url}?run={site.run_id}", wait_until="networkidle")
    page.wait_for_selector("#chart svg", timeout=20_000)
    expect(page.locator("body")).to_have_attribute("data-view", "detail")
    expect(page.locator("#run-meta")).to_contain_text("configured")


def test_back_button_returns_to_overview(overview):
    _click_first_point(overview)
    overview.wait_for_function("() => new URLSearchParams(location.search).has('run')", timeout=10_000)
    overview.go_back()
    overview.wait_for_function("() => !new URLSearchParams(location.search).has('run')", timeout=10_000)
    expect(overview.locator("body")).to_have_attribute("data-view", "overview")


def test_sidebar_collapses(overview):
    expect(overview.locator("#app-root")).not_to_have_class(COLLAPSED)
    overview.locator("#btn-sidebar-toggle").click()
    expect(overview.locator("#app-root")).to_have_class(COLLAPSED, timeout=5_000)


def test_default_brand_is_karaoke(overview):
    # design-tokens.json sets defaultBrand: karaoke.
    assert overview.locator("#brand-picker").input_value() == "karaoke"


def test_brand_switch_applies_palette(overview):
    overview.locator("#brand-picker").select_option("v2ai")
    accent = overview.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    assert accent.lower() == "#fec40e"  # V2 AI signature amber
    assert overview.evaluate("() => localStorage.getItem('obs-brand')") == "v2ai"


def test_run_logs_expand(page: Page, site):
    page.goto(f"{site.url}?run={site.run_id}", wait_until="networkidle")
    page.wait_for_selector("#chart svg", timeout=20_000)
    expect(page.locator("#run-logs-summary")).to_contain_text("Run logs")
    # Collapsed by default; expands on click; one row per node (the seeded run has 4).
    assert page.locator("#run-logs").evaluate("el => el.open") is False
    page.locator("#run-logs-summary").click()
    assert page.locator("#run-logs").evaluate("el => el.open") is True
    expect(page.locator("#run-logs-body > div")).to_have_count(4)


def test_time_brush_narrows_window(page: Page, site):
    page.goto(f"{site.url}?run={site.run_id}", wait_until="networkidle")
    page.wait_for_selector("#chart svg", timeout=20_000)
    # Full window ⇒ the selected-range fill spans the whole track.
    assert page.locator("#brush-fill").evaluate("el => el.style.width") == "100%"
    # Drag the end handle to the midpoint (500/1000) and fire input.
    page.locator("#brush-end").evaluate("el => { el.value = '500'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    assert page.locator("#brush-fill").evaluate("el => el.style.width") == "50%"
    expect(page.locator("#brush-readout")).to_contain_text("of")
