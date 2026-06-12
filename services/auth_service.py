"""
Auth service: handle login Stockbit (via Obscura) + token caching.

Token flow:
  1. Check local cache (JSON file) — return if valid
  2. If expired/missing — login via Obscura headless browser
  3. Cache new token with TTL

Token disimpan ke file JSON lokal supaya proses tidak perlu
re-login lewat browser tiap restart.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.config import config
from core.logger import logger


class AuthService:
    def __init__(self) -> None:
        self._cache_path = Path(config.STOCKBIT_TOKEN_CACHE_PATH)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)

    async def get_token(self) -> str:
        """Return token. Priority: env var > cache > Obscura login."""
        # 1. Direct bearer token from env (most reliable)
        env_token = config.STOCKBIT_BEARER_TOKEN
        if env_token:
            logger.debug("auth: using env STOCKBIT_BEARER_TOKEN")
            return env_token

        # 2. Cached token
        cached = self._read_cache()
        if cached and not self._is_expired(cached):
            logger.debug("auth: using cached token")
            return cached["token"]

        # 3. Login via Obscura
        return await self.refresh_token()

    async def refresh_token(self, force: bool = False) -> str:
        """Login ulang via Obscura, simpan token baru ke cache.

        Flow:
          1. Navigate ke stockbit.com/login
          2. Fill credentials
          3. Intercept response yang bawa access_token
          4. Return token
        """
        logger.info("auth: refreshing Stockbit token via Obscura")

        if not config.STOCKBIT_USERNAME or not config.STOCKBIT_PASSWORD:
            logger.error("auth: STOCKBIT_USERNAME/PASSWORD not configured")
            return ""

        try:
            from providers.obscura_client import obscura_client

            async with obscura_client.page() as page:
                await page.goto("https://stockbit.com/login", wait_until="networkidle")

                # Fill login form
                await page.fill(
                    "input[name='username'], input[type='email'], #username",
                    config.STOCKBIT_USERNAME,
                )
                await page.fill(
                    "input[name='password'], input[type='password'], #password",
                    config.STOCKBIT_PASSWORD,
                )

                # Intercept auth response
                token = None

                async def handle_response(response):
                    nonlocal token
                    url = response.url
                    if "auth" in url or "login" in url or "token" in url:
                        try:
                            data = await response.json()
                            # Try common token field names
                            for key in ["access_token", "token", "data.token"]:
                                if key in data:
                                    token = data[key]
                                    break
                                # Nested: data.token
                                if "data" in data and isinstance(data["data"], dict):
                                    if "token" in data["data"]:
                                        token = data["data"]["token"]
                                        break
                        except Exception:
                            pass

                page.on("response", handle_response)

                # Submit form
                await page.click(
                    "button[type='submit'], .login-button, button:has-text('Login')"
                )

                # Wait for navigation/response
                await page.wait_for_load_state("networkidle")
                # Give extra time for token capture
                await page.wait_for_timeout(2000)

                # Fallback: try reading token from cookies
                if not token:
                    cookies = await page.context.cookies()
                    for cookie in cookies:
                        if "token" in cookie["name"].lower():
                            token = cookie["value"]
                            break

                # Fallback: try localStorage
                if not token:
                    token = await page.evaluate(
                        "() => localStorage.getItem('access_token') || "
                        "localStorage.getItem('token') || "
                        "localStorage.getItem('sb_token')"
                    )

            if token:
                logger.info("auth: token acquired via Obscura")
                self._write_cache(token)
                return token
            else:
                logger.error("auth: could not capture token from login flow")
                # Return stale token if available
                stale = self._read_cache()
                return stale["token"] if stale else ""

        except Exception as exc:
            logger.error(f"auth: Obscura login failed: {exc}")
            # Return stale cached token as last resort
            stale = self._read_cache()
            return stale["token"] if stale else ""

    def _read_cache(self) -> dict | None:
        if not self._cache_path.exists():
            return None
        try:
            return json.loads(self._cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, token: str) -> None:
        # Stockbit token TTL observasi: ~6 jam (belum confirmed, adjust later)
        data = {"token": token, "fetched_at": time.time(), "ttl_seconds": 6 * 3600}
        self._cache_path.write_text(json.dumps(data))
        logger.debug("auth: token cached")

    @staticmethod
    def _is_expired(cached: dict) -> bool:
        fetched_at = cached.get("fetched_at", 0)
        ttl = cached.get("ttl_seconds", 0)
        return (time.time() - fetched_at) > ttl


auth_service = AuthService()
