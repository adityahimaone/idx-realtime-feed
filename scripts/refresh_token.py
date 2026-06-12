#!/usr/bin/env python3
"""Refresh Stockbit bearer token via existing Brave/Chrome session (CDP).

Usage:
    # 1. Start Brave with remote debugging (one-time):
    /Applications/Brave\ Browser.app/Contents/MacOS/Brave\ Browser \
        --remote-debugging-port=9222

    # 2. Login ke stockbit.com di browser tab

    # 3. Run script:
    uv run python scripts/refresh_token.py

Script akan:
  - Connect ke browser via CDP (port 9222)
  - Navigate ke Stockbit watchlist
  - Intercept exodus API request → capture Bearer token
  - Update .env dengan token baru
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
STOCKBIT_URL = "https://stockbit.com/watchlist"
ENV_PATH = Path(__file__).parent.parent / ".env"


async def refresh_token() -> str | None:
    from playwright.async_api import async_playwright

    token: str | None = None

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"✗ Can't connect to Brave on port {CDP_PORT}: {e}")
            print()
            print("  Start Brave with remote debugging:")
            print("    /Applications/Brave\\ Browser.app/Contents/MacOS/Brave\\ Browser \\")
            print("        --remote-debugging-port=9222")
            print()
            print("  Or Chrome:")
            print("    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
            print("        --remote-debugging-port=9222")
            return None

        context = browser.contexts[0]
        page = await context.new_page()

        # Intercept exodus API requests for token
        async def handle_request(request):
            nonlocal token
            if token:
                return
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer ") and len(auth) > 100:
                t = auth.split(" ", 1)[1]
                # Validate it looks like a JWT
                if t.count(".") == 2:
                    token = t
                    print(f"✓ Token captured from: {request.url}")

        page.on("request", handle_request)

        print(f"→ Navigating to {STOCKBIT_URL} ...")
        await page.goto(STOCKBIT_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)  # let API calls finish

        if not token:
            # Try to trigger an exodus call by scrolling/refreshing
            print("→ No token yet, trying refresh...")
            await page.reload(wait_until="networkidle")
            await asyncio.sleep(3)

        await browser.close()
        return token


def update_env(token: str) -> bool:
    if not ENV_PATH.exists():
        print(f"✗ .env not found at {ENV_PATH}")
        return False

    with open(ENV_PATH) as f:
        content = f.read()

    # Replace STOCKBIT_BEARER_TOKEN line
    new_content = re.sub(
        r"^STOCKBIT_BEARER_TOKEN=.*$",
        f"STOCKBIT_BEARER_TOKEN={token}",
        content,
        flags=re.MULTILINE,
    )

    if new_content == content:
        print("✗ STOCKBIT_BEARER_TOKEN not found in .env")
        return False

    with open(ENV_PATH, "w") as f:
        f.write(new_content)

    print(f"✓ .env updated at {ENV_PATH}")
    return True


def verify_token(token: str) -> bool:
    """Quick decode JWT header to verify it looks valid."""
    try:
        import base64

        # Just decode the header part
        header_b64 = token.split(".")[0]
        # Add padding
        padding = 4 - len(header_b64) % 4
        if padding != 4:
            header_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(header_b64)
        header = json.loads(decoded)
        print(f"  JWT issuer: {header.get('iss', '?')}")
        print(f"  JWT algo:   {header.get('alg', '?')}")
        return True
    except Exception:
        return True  # non-critical, pass


async def main():
    print("=== Stockbit Token Refresher ===\n")

    token = await refresh_token()

    if not token:
        print("\n✗ Failed to capture token.")
        print("  Pastikan:")
        print("  1. Brave/Chrome running with --remote-debugging-port=9222")
        print("  2. Udah login ke stockbit.com di browser")
        print("  3. Koneksi internet aktif")
        sys.exit(1)

    print(f"\n✓ Token: {token[:32]}...{token[-8:]}")
    print(f"  Length: {len(token)} chars")
    verify_token(token)

    if update_env(token):
        print("\n✔ Done! Now run: uv run python main.py")
    else:
        print("\n✗ .env update failed. Manual:")
        print(f"  STOCKBIT_BEARER_TOKEN={token}")


if __name__ == "__main__":
    asyncio.run(main())
