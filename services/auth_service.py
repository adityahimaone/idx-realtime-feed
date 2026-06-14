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
        # 1. Direct bearer token from env (check if valid and not expired)
        env_token = config.STOCKBIT_BEARER_TOKEN
        if env_token and not self._is_jwt_expired(env_token):
            logger.debug("auth: using valid env STOCKBIT_BEARER_TOKEN")
            return env_token

        # 2. Cached token
        cached = self._read_cache()
        if cached and not self._is_expired(cached) and not self._is_jwt_expired(cached["token"]):
            logger.debug("auth: using valid cached token")
            # Also update config.STOCKBIT_BEARER_TOKEN in case env was old
            config.STOCKBIT_BEARER_TOKEN = cached["token"]
            return cached["token"]

        # 3. Login via Obscura (expired or missing)
        logger.info("auth: token is missing or expired. Refreshing...")
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

                # Robust element filling/clicking helpers to bypass strict Playwright visibility blocks on headless browsers
                async def robust_fill(selector: str, value: str):
                    js_code = """
                    (selector, val) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        const nativeValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                        nativeValueSetter.call(el, val);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    """
                    try:
                        await page.wait_for_selector(selector, state="attached", timeout=15000)
                        success = await page.evaluate(f"({js_code})('{selector}', '{value}')")
                        if not success:
                            logger.error(f"auth: selector {selector} not found in DOM")
                    except Exception as e:
                        logger.error(f"auth: JS fill error for {selector}: {e}")

                async def robust_submit(selector_in_form: str):
                    js_code = """
                    (selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        const form = el.form;
                        if (form) {
                            form.submit();
                            return true;
                        }
                        return false;
                    }
                    """
                    try:
                        success = await page.evaluate(f"({js_code})('{selector_in_form}')")
                        if not success:
                            # Fallback click via JS
                            await page.evaluate("document.querySelector('button[type=\"submit\"], button:has-text(\"Masuk\"), button:has-text(\"Log In\")').click()")
                    except Exception as e:
                        logger.error(f"auth: JS submit error: {e}")

                # Fill username using id=username as primary
                username_selector = "#username"
                if await page.locator(username_selector).count() == 0:
                    username_selector = "input[name='username']"
                await robust_fill(username_selector, config.STOCKBIT_USERNAME)

                # Fill password using id=password as primary
                password_selector = "#password"
                if await page.locator(password_selector).count() == 0:
                    password_selector = "input[name='password']"
                await robust_fill(password_selector, config.STOCKBIT_PASSWORD)

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

                # Submit form via JS submit() or JS click
                await robust_submit(password_selector)

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
                self._write_env(token)
                config.STOCKBIT_BEARER_TOKEN = token  # Update in-memory
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

    @staticmethod
    def _is_jwt_expired(token: str) -> bool:
        """Decode JWT payload without verifying signature to check expiration."""
        try:
            import base64
            parts = token.split(".")
            if len(parts) != 3:
                return True
            
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            decoded = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(decoded)
            
            exp = payload.get("exp")
            if not exp:
                return False
            
            # Allow 60 seconds buffer
            return time.time() > (exp - 60)
        except Exception:
            return True

    def _write_env(self, token: str) -> None:
        """Write the token back to the .env file so it is persistent."""
        import re
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists():
            return
        try:
            content = env_path.read_text()
            if "STOCKBIT_BEARER_TOKEN=" in content:
                new_content = re.sub(
                    r"^STOCKBIT_BEARER_TOKEN=.*$",
                    f"STOCKBIT_BEARER_TOKEN={token}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                new_content = content.rstrip() + f"\nSTOCKBIT_BEARER_TOKEN={token}\n"
            env_path.write_text(new_content)
            logger.info("auth: .env file updated with new token")
        except Exception as e:
            logger.error(f"auth: failed to write token to .env: {e}")


auth_service = AuthService()
