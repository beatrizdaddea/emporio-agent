"""Real-browser UI scenarios with reproducible screenshots, videos, and traces."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Locator, Page, expect

from emporio.ui import MODE_LOCAL_DETERMINISTIC

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = PROJECT_ROOT / "examples" / "ui-evidence"
VIEWPORT = {"width": 1440, "height": 1000}
RESPONSE_TIMEOUT_MS = 60_000


@dataclass
class EvidencePage:
    """Browser page plus captured runtime diagnostics for one scenario."""

    page: Page
    slug: str
    console_errors: list[str] = field(default_factory=list)
    console_warnings: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)

    def send_message(self, prompt: str) -> Locator:
        messages = self.page.locator('[data-testid="stChatMessage"]')
        previous_count = messages.count()
        chat_input = self.page.get_by_placeholder(
            "Ask about products, promotions, orders, return deadlines, or store policies..."
        )
        chat_input.fill(prompt)
        chat_input.press("Enter")
        expect(messages).to_have_count(previous_count + 2, timeout=RESPONSE_TIMEOUT_MS)
        assistant = messages.nth(previous_count + 1)
        expect(assistant).to_be_visible()
        return assistant

    def expand_technical_evidence(self, assistant: Locator) -> None:
        assistant.get_by_text("Technical evidence", exact=True).click()
        expect(assistant.get_by_text("Model:", exact=False)).to_be_visible()

    def capture_success(self) -> None:
        screenshot_path = EVIDENCE_ROOT / "screenshots" / f"{self.slug}.png"
        self.page.set_viewport_size({"width": VIEWPORT["width"], "height": 1600})
        first_message = self.page.locator('[data-testid="stChatMessage"]').first
        first_message.evaluate("element => element.scrollIntoView({block: 'start'})")
        self.page.screenshot(path=str(screenshot_path), full_page=False)

    def assert_console_health(self) -> None:
        assert not self.console_errors, f"Browser console errors: {self.console_errors}"
        assert not self.page_errors, f"Uncaught page errors: {self.page_errors}"


def _record_console(message: ConsoleMessage, evidence: EvidencePage) -> None:
    if message.type == "error":
        evidence.console_errors.append(message.text)
    elif message.type == "warning":
        evidence.console_warnings.append(message.text)


def _prepare_app(page: Page, app_url: str) -> None:
    page.goto(app_url, wait_until="domcontentloaded", timeout=30_000)
    expect(page).to_have_title(
        "Empório da Música — Support Agent Evidence UI",
        timeout=30_000,
    )
    expect(
        page.get_by_text("Empório da Música — Support Agent", exact=False).first
    ).to_be_visible()
    expect(page.get_by_text("Startup / Configuration Error", exact=False)).to_have_count(0)

    execution_mode = page.get_by_role("combobox").first
    execution_mode.click()
    page.get_by_role("option", name=MODE_LOCAL_DETERMINISTIC, exact=True).click()
    expect(page.get_by_text(MODE_LOCAL_DETERMINISTIC, exact=False).first).to_be_visible()


@pytest.fixture
def evidence_page(browser: Browser, app_url: str):
    """Create an isolated recorded browser context for each named scenario."""

    @contextmanager
    def create(slug: str) -> Iterator[EvidencePage]:
        for directory in (
            EVIDENCE_ROOT / "screenshots",
            EVIDENCE_ROOT / "screenshots" / "failures",
            EVIDENCE_ROOT / "videos",
            EVIDENCE_ROOT / "videos" / "failures",
            EVIDENCE_ROOT / "traces",
            EVIDENCE_ROOT / "traces" / "failures",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        raw_video_dir = EVIDENCE_ROOT / ".raw-videos" / slug
        raw_video_dir.mkdir(parents=True, exist_ok=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(raw_video_dir),
            record_video_size=VIEWPORT,
            locale="pt-BR",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        evidence = EvidencePage(page=page, slug=slug)
        page.on("console", lambda message: _record_console(message, evidence))
        page.on("pageerror", lambda error: evidence.page_errors.append(str(error)))
        failed = False
        try:
            _prepare_app(page, app_url)
            yield evidence
        except BaseException:
            failed = True
            failure_path = EVIDENCE_ROOT / "screenshots" / "failures" / f"{slug}.png"
            page.screenshot(path=str(failure_path), full_page=True)
            raise
        finally:
            artifact_group = "failures" if failed else None
            trace_dir = EVIDENCE_ROOT / "traces"
            video_dir = EVIDENCE_ROOT / "videos"
            if artifact_group:
                trace_dir /= artifact_group
                video_dir /= artifact_group
            trace_path = trace_dir / f"{slug}.zip"
            context.tracing.stop(path=str(trace_path))
            video = page.video
            context.close()
            if video is not None:
                video.save_as(video_dir / f"{slug}.webm")
            shutil.rmtree(raw_video_dir, ignore_errors=True)

    return create


@pytest.mark.e2e
def test_01_product_search_pt(evidence_page) -> None:
    with evidence_page("01-product-search-pt") as evidence:
        assistant = evidence.send_message("Quais violões vocês têm por até R$ 1.000?")
        expect(assistant).to_contain_text("Estes são os produtos correspondentes no catálogo")
        expect(assistant).to_contain_text("Tagima Memphis AC-39 Nylon Natural")
        expect(assistant).to_contain_text("R$ 429.90")
        expect(assistant).to_contain_text("Yamaha C40 Nylon Natural")
        expect(assistant).to_contain_text("R$ 599.90")
        expect(assistant).not_to_contain_text("Giannini GF-3D Dreadnought Sunburst")
        expect(assistant).not_to_contain_text("Shelby SN-7C 7 Cordas Nylon Natural")
        evidence.expand_technical_evidence(assistant)
        expect(assistant).to_contain_text("call search_products")
        expect(assistant).to_contain_text('"available_only": true')
        expect(assistant).to_contain_text('"max_price_brl": 1000.0')
        evidence.capture_success()
        evidence.assert_console_health()


@pytest.mark.e2e
def test_02_product_search_en(evidence_page) -> None:
    with evidence_page("02-product-search-en") as evidence:
        assistant = evidence.send_message("Which guitars do you have under R$1,000?")
        expect(assistant).to_contain_text("Here are the matching products from our catalog")
        expect(assistant).to_contain_text("Tagima Memphis AC-39 Nylon Natural")
        expect(assistant).to_contain_text("R$ 429.90")
        expect(assistant).to_contain_text("Yamaha C40 Nylon Natural")
        expect(assistant).not_to_contain_text("Takamine GD20 Dreadnought Natural")
        evidence.expand_technical_evidence(assistant)
        expect(assistant).to_contain_text("call search_products")
        expect(assistant).to_contain_text('"category": "acoustic_classical_guitars"')
        expect(assistant).to_contain_text('"max_price_brl": 1000.0')
        evidence.capture_success()
        evidence.assert_console_health()


@pytest.mark.e2e
def test_03_store_policy(evidence_page) -> None:
    with evidence_page("03-store-policy") as evidence:
        assistant = evidence.send_message("Qual é a política de devolução da loja?")
        expect(assistant).to_contain_text("Política da Loja §4.1")
        expect(assistant).to_contain_text("7 (sete) dias corridos")
        expect(assistant).to_contain_text("embalagem original")
        expect(assistant).to_contain_text("10 dias úteis")
        expect(assistant).to_contain_text("frete de devolução é por conta da loja")
        evidence.expand_technical_evidence(assistant)
        expect(assistant).to_contain_text("call search_policy")
        expect(assistant).to_contain_text("policy §4.1")
        evidence.capture_success()
        evidence.assert_console_health()


@pytest.mark.e2e
def test_04_multi_tool_conversation(evidence_page) -> None:
    with evidence_page("04-multi-tool-conversation") as evidence:
        assistant = evidence.send_message(
            "Comprei o violão do pedido 4 e quero saber se posso devolver. Como funciona?"
        )
        expect(assistant).to_contain_text("Pedido #4")
        expect(assistant).to_contain_text("Giannini GF-3D Dreadnought Sunburst")
        expect(assistant).to_contain_text("window_expired")
        expect(assistant).to_contain_text("Política da Loja §4.1")
        expect(assistant).to_contain_text("Não verificado")
        expect(assistant).to_contain_text("data real de entrega")
        evidence.expand_technical_evidence(assistant)
        expect(assistant).to_contain_text("call get_order_status")
        expect(assistant).to_contain_text("call check_return_eligibility")
        expect(assistant).to_contain_text("call search_policy")
        evidence.capture_success()
        evidence.assert_console_health()


@pytest.mark.e2e
def test_05_out_of_scope(evidence_page) -> None:
    with evidence_page("05-out-of-scope") as evidence:
        assistant = evidence.send_message("Qual é a capital da França?")
        expect(assistant).to_contain_text("Posso ajudar apenas")
        expect(assistant).to_contain_text("Empório da Música")
        expect(assistant).not_to_contain_text("Paris")
        evidence.expand_technical_evidence(assistant)
        expect(assistant).to_contain_text("No tools invoked")
        evidence.capture_success()
        evidence.assert_console_health()


@pytest.mark.e2e
def test_06_language_switch(evidence_page) -> None:
    with evidence_page("06-language-switch") as evidence:
        first_assistant = evidence.send_message("Quais violões vocês têm por até R$ 1.000?")
        expect(first_assistant).to_contain_text("Estes são os produtos correspondentes")

        second_assistant = evidence.send_message("Which of those guitars is the cheapest?")
        expect(second_assistant).to_contain_text("The cheapest matching product is")
        expect(second_assistant).to_contain_text("Tagima Memphis AC-39 Nylon Natural")
        expect(second_assistant).to_contain_text("R$ 429.90")
        expect(evidence.page.locator('[data-testid="stChatMessage"]')).to_have_count(4)
        expect(first_assistant).to_be_visible()
        evidence.expand_technical_evidence(second_assistant)
        expect(second_assistant).to_contain_text("call search_products")
        evidence.capture_success()
        evidence.assert_console_health()
