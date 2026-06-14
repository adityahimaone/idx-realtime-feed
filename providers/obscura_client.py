"""
Wrapper untuk Obscura headless browser.

Obscura jalan sebagai CDP server (`obscura serve --port 9222 --stealth`),
dan karena Playwright Python support `connect_over_cdp()` ke endpoint CDP
manapun, kita bisa pakai obscura sebagai drop-in replacement Chrome/Selenium
tanpa perlu binding Rust khusus.

Asumsi: obscura sudah jalan sebagai service terpisah (PM2 process lain di
VPS), bukan di-spawn dari sini. Kalau mau auto-spawn, tambahkan subprocess
launch di `start()`.

    obscura serve --port 9222 --stealth
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from core.config import config
from core.logger import logger


class ObscuraClient:
    """Thin wrapper di sekitar Playwright connect_over_cdp -> Obscura."""

    def __init__(self, cdp_url: str | None = None) -> None:
        self.cdp_url = cdp_url or config.OBSCURA_CDP_URL

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Context manager: yield satu Page baru, auto-close setelah selesai."""
        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.connect_over_cdp(self.cdp_url)
            
            # Context-level proxy options if configured
            proxy_args = {}
            if config.PROXY_SERVER:
                proxy_args["proxy"] = {
                    "server": config.PROXY_SERVER
                }
                if config.PROXY_USERNAME:
                    proxy_args["proxy"]["username"] = config.PROXY_USERNAME
                if config.PROXY_PASSWORD:
                    proxy_args["proxy"]["password"] = config.PROXY_PASSWORD
                    
            context: BrowserContext = await browser.new_context(**proxy_args)
            page = await context.new_page()
            try:
                logger.debug(f"obscura: page opened via {self.cdp_url} (proxy: {config.PROXY_SERVER or 'none'})")
                yield page
            finally:
                await context.close()
                await browser.close()


obscura_client = ObscuraClient()


# ---------------------------------------------------------------------------
# TODO (Phase 2): contoh penggunaan untuk login flow Stockbit
# ---------------------------------------------------------------------------
#
# async def login_stockbit(username: str, password: str) -> str:
#     """Login ke Stockbit web, return auth token dari response/cookie."""
#     async with obscura_client.page() as page:
#         await page.goto("https://stockbit.com/login")
#         await page.fill("input[name='username']", username)
#         await page.fill("input[name='password']", password)
#
#         # Tangkap network response yang membawa token, misal lewat
#         # page.on("response", ...) sebelum submit form.
#         async with page.expect_response(lambda r: "auth" in r.url) as resp_info:
#             await page.click("button[type='submit']")
#         response = await resp_info.value
#         data = await response.json()
#         return data["access_token"]
