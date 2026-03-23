"""browser_scraper.py — Playwright-based web scraper for SHARD study pipeline.

Extracted from study_agent.py as part of SSJ3 Phase 1: Core Hardening.
"""
import asyncio
import base64
import random
from typing import Callable, List, Dict, Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth

from study_utils import ProgressTracker


class StudyBrowserScraper:
    """Handles all Playwright browser automation for the AGGREGATE phase.

    Args:
        user_agents: List of user agent strings for rotation.
    """

    DEFAULT_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    ]

    def __init__(self, user_agents: Optional[List[str]] = None):
        self.user_agents = user_agents or self.DEFAULT_USER_AGENTS
        self.browser = None
        self.playwright = None
        self.bctx = None

    async def _init(self, headless: bool = False):
        """Launch browser — headless=False so Boss can see it working."""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            )
            self.bctx = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=random.choice(self.user_agents),
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            # Anti-detection: stealth is applied per-page via stealth_async()

    async def _close(self):
        if self.browser:
            try:
                await self.browser.close()
                await self.playwright.stop()
            except:
                pass
            self.browser = self.playwright = self.bctx = None

    async def _take_screenshot(self, page: Page, label: str = "", on_web_data_fn=None):
        """Capture screenshot and send to frontend if callback is set."""
        try:
            screenshot = await page.screenshot(type="jpeg", quality=60)
            b64 = base64.b64encode(screenshot).decode("utf-8")
            if on_web_data_fn:
                on_web_data_fn({
                    "image": b64,
                    "log": f"[STUDY] {label}" if label else "[STUDY] Browsing..."
                })
        except:
            pass

    async def _handle_cookies(self, page: Page):
        """Try to dismiss common cookie consent banners."""
        cookie_selectors = [
            # Common cookie button selectors
            "button:has-text('Accept')",
            "button:has-text('Accetta')",
            "button:has-text('Accept all')",
            "button:has-text('Accetta tutto')",
            "button:has-text('Accetta tutti')",
            "button:has-text('Accept All Cookies')",
            "button:has-text('Allow all')",
            "button:has-text('Consenti tutti')",
            "button:has-text('Got it')",
            "button:has-text('OK')",
            "button:has-text('Agree')",
            "[id*='accept']",
            "[id*='consent']",
            "[class*='accept']",
            "[class*='consent'] button",
            "#onetrust-accept-btn-handler",
            ".cc-accept",
            ".cookie-accept",
            "#cookie-accept",
            "[data-testid='cookie-accept']",
        ]

        for selector in cookie_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    print(f"[COOKIES] Dismissed with: {selector}")
                    await asyncio.sleep(0.5)
                    return True
            except:
                continue
        return False

    async def _handle_captcha(self, page: Page) -> bool:
        """Detect captcha and wait for manual resolution if browser is visible."""
        captcha_indicators = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            "[class*='captcha']",
            "[id*='captcha']",
            "iframe[src*='challenge']",
            ".g-recaptcha",
            "#cf-challenge-running",  # Cloudflare
        ]

        for selector in captcha_indicators:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=500):
                    print(f"[CAPTCHA] ⚠️ Captcha detected! Waiting for manual resolution...")
                    await self._take_screenshot(page, "⚠️ CAPTCHA DETECTED - Solve manually!")

                    # Wait up to 60 seconds for captcha to disappear
                    for _ in range(60):
                        await asyncio.sleep(1)
                        try:
                            if not await el.is_visible(timeout=300):
                                print("[CAPTCHA] ✅ Captcha resolved!")
                                return True
                        except:
                            print("[CAPTCHA] ✅ Captcha resolved!")
                            return True

                    print("[CAPTCHA] ❌ Timeout waiting for captcha resolution")
                    return False
            except:
                continue
        return True  # No captcha found = OK

    async def _safe_goto(self, page: Page, url: str, label: str = "", on_web_data_fn=None) -> bool:
        """Navigate to URL with cookie/captcha handling and screenshot."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(0.5)

            # Handle cookies
            await self._handle_cookies(page)

            # Check for captcha
            captcha_ok = await self._handle_captcha(page)
            if not captcha_ok:
                return False

            # Send screenshot to frontend
            await self._take_screenshot(page, label or f"Loaded: {url[:60]}", on_web_data_fn=on_web_data_fn)
            return True

        except Exception as e:
            print(f"[BROWSER] Navigation failed: {url} — {e}")
            return False

    async def scrape_sources(
        self,
        sources: List[Dict],
        max_sources: int = 6,
        progress: ProgressTracker = None,
        on_web_data_fn: Callable = None,
    ) -> str:
        """Scrape and aggregate text from a list of sources.

        Browser is always closed via finally — no leak on crash.
        Returns concatenated text from all successfully scraped sources.
        """
        print(f"[AGGREGATE] Scraping {max_sources} sources...")

        await self._init(headless=False)
        all_text = ""

        try:
            for idx, source in enumerate(sources[:max_sources]):
                url = source["url"]
                if progress:
                    progress.set_phase("AGGREGATE", idx / max_sources)

                page = None
                try:
                    page = await self.bctx.new_page()
                    await Stealth().apply_stealth_async(page)
                    success = await self._safe_goto(page, url, f"Reading [{idx+1}/{max_sources}]: {source['title'][:50]}", on_web_data_fn=on_web_data_fn)

                    if success:
                        content = await page.content()
                        soup = BeautifulSoup(content, "html.parser")
                        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
                            tag.extract()
                        text = soup.get_text(separator="\n", strip=True)
                        text = "\n".join(line for line in text.splitlines() if len(line.strip()) >= 2)
                        all_text += f"\n\n--- SOURCE: {source['title']} ({url}) ---\n{text[:3000]}"
                        print(f"[AGGREGATE] ✅ [{idx+1}/{max_sources}] {source['title'][:50]} ({len(text)} chars)")
                    else:
                        print(f"[AGGREGATE] ❌ [{idx+1}/{max_sources}] Failed: {url}")

                    await asyncio.sleep(0.8)

                except Exception as e:
                    print(f"[AGGREGATE] ❌ Failed {url}: {e}")
                finally:
                    if page:
                        try:
                            await page.close()
                        except Exception:
                            pass
        finally:
            await self._close()

        print(f"[AGGREGATE] Total raw text: {len(all_text)} chars")
        return all_text
