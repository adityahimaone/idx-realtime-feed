#!/usr/bin/env python3
"""Refresh Stockbit bearer token via Brave, Chrome, Edge or Playwright.

Usage:
    uv run python scripts/refresh_token.py

Features:
  - Detects if port 9222 is already open.
  - Interactive browser selector (Brave, Chrome, Edge, or Playwright Chromium).
  - Automatically launches the selected browser with remote debugging on port 9222.
  - Custom debug profiles to avoid profile locks and preserve login session.
  - Beautiful unicode animation spinner while capturing token.
  - Auto-updates .env (creates variable if missing).
  - Prompts and starts main.py automatically.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import socket
import shutil
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

# Add project root to sys.path to allow core.* imports
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
STOCKBIT_URL = "https://stockbit.com/watchlist"
ENV_PATH = Path(__file__).parent.parent / ".env"


def is_port_open(port: int) -> bool:
    """Check if the given port is open on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def get_installed_browsers() -> dict[str, str]:
    """Detect installed browsers on the system that support CDP."""
    paths = {}
    if sys.platform == "darwin":
        paths = {
            "Brave Browser": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "Google Chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "Microsoft Edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        }
    elif sys.platform == "win32":
        paths = {
            "Google Chrome": os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            "Brave Browser": os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            "Microsoft Edge": os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")
        }
    else:
        # Linux standard command line names
        for cmd in ["google-chrome", "brave-browser", "microsoft-edge"]:
            path = shutil.which(cmd)
            if path:
                name = cmd.replace("-", " ").title()
                paths[name] = path
                
    # Filter only those that actually exist
    return {name: path for name, path in paths.items() if os.path.exists(path) or shutil.which(path)}


async def refresh_token(browser_choice: str, browser_path: str | None) -> str | None:
    from playwright.async_api import async_playwright

    token: str | None = None
    proc: subprocess.Popen | None = None
    console = Console()

    # Launch browser if needed
    if browser_choice != "Connect to existing running browser (port 9222)" and browser_choice != "Playwright Chromium":
        if is_port_open(CDP_PORT):
            console.print(f"[yellow]ℹ Port {CDP_PORT} is already open. Connecting to existing browser...[/yellow]")
        else:
            if not browser_path:
                console.print(f"[red]✗ Browser path not found for {browser_choice}[/red]")
                return None
            
            # Use a separate user-data-dir to prevent conflicts with normal running instances
            profile_name = browser_choice.lower().replace(" ", "_")
            user_data_dir = os.path.expanduser(f"~/.cache/stockbit_{profile_name}_debug")
            os.makedirs(user_data_dir, exist_ok=True)
            
            console.print(f"→ Launching [bold]{browser_choice}[/bold] with remote debugging on port {CDP_PORT}...")
            cmd = [
                browser_path,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={user_data_dir}",
                "about:blank"
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for the port to open
            success = False
            for _ in range(20):
                if is_port_open(CDP_PORT):
                    success = True
                    break
                await asyncio.sleep(0.5)
                
            if not success:
                console.print(f"[red]✗ Failed to start {browser_choice} on port {CDP_PORT}.[/red]")
                if proc:
                    proc.kill()
                return None
            console.print(f"[green]✓ {browser_choice} started successfully.[/green]")

    async with async_playwright() as p:
        try:
            if browser_choice == "Playwright Chromium":
                console.print("→ Launching Playwright Default Chromium (persistent context)...")
                user_data_dir = os.path.expanduser("~/.cache/stockbit_playwright_debug")
                os.makedirs(user_data_dir, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    viewport={"width": 1280, "height": 800}
                )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                # Connect over CDP
                browser = await p.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0]
                page = await context.new_page()
        except Exception as e:
            console.print(f"[red]✗ Playwright failed to connect/launch: {e}[/red]")
            if "executable doesn't exist" in str(e).lower() or "playwright install" in str(e).lower():
                console.print("\n[yellow]💡 Playwright browser binaries might be missing. You can install them by running:[/yellow]")
                console.print("   [bold]uv run playwright install[/bold]\n")
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
            return None

        # Intercept exodus API requests for token
        async def handle_request(request):
            nonlocal token
            if token:
                return
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer ") and len(auth) > 100:
                t = auth.split(" ", 1)[1]
                if t.count(".") == 2:
                    token = t

        page.on("request", handle_request)

        LOGIN_URL = "https://stockbit.com/login"
        console.print(f"→ Navigating to {LOGIN_URL} ...")
        try:
            await page.goto(LOGIN_URL, wait_until="load", timeout=45000)
        except Exception as e:
            pass

        # Check if we need to log in (auto-login support for headless VPS / Obscura)
        await asyncio.sleep(3)  # Wait for redirects (in case already logged in)
        current_url = page.url
        is_login_page = "login" in current_url.lower()
        if not is_login_page:
            try:
                is_login_page = await page.locator("input[name='username']").count() > 0 or await page.locator("#username").count() > 0
            except Exception:
                is_login_page = False

        # Robust element filling/clicking helpers to bypass strict Playwright visibility blocks on headless browsers
        async def robust_fill(selector: str, value: str):
            try:
                await page.wait_for_selector(selector, state="attached", timeout=10000)
                await page.fill(selector, value, timeout=5000)
                return
            except Exception:
                pass
            try:
                await page.evaluate(f"document.querySelector('{selector}').focus()")
                await page.keyboard.press("Meta+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.type(value)
                return
            except Exception:
                pass
            try:
                await page.evaluate(f"""
                    const el = document.querySelector('{selector}');
                    el.value = '{value}';
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                """)
            except Exception as e:
                console.print(f"[yellow]⚠️ Failed to fill {selector}: {e}[/yellow]")

        async def robust_click(selector: str):
            try:
                await page.wait_for_selector(selector, state="attached", timeout=10000)
                await page.click(selector, timeout=5000)
                return
            except Exception:
                pass
            try:
                await page.evaluate(f"document.querySelector('{selector}').click()")
            except Exception as e:
                console.print(f"[yellow]⚠️ Failed to click {selector}: {e}[/yellow]")

        if is_login_page:
            console.print("→ Detected login page. Attempting automatic login using credentials from .env...")
            try:
                from core.config import config
                username = config.STOCKBIT_USERNAME
                password = config.STOCKBIT_PASSWORD

                if not username or not password:
                    console.print("[yellow]⚠️ STOCKBIT_USERNAME or STOCKBIT_PASSWORD not set in .env.[/yellow]")
                    console.print("[yellow]Please make sure they are set for auto-login to work on headless environments.[/yellow]")
                else:
                    # Fill username using id=username as primary selector
                    username_selector = "#username"
                    if await page.locator(username_selector).count() == 0:
                        username_selector = "input[name='username']"
                    
                    console.print("→ Filling username...")
                    await robust_fill(username_selector, username)

                    # Fill password using id=password as primary selector
                    password_selector = "#password"
                    if await page.locator(password_selector).count() == 0:
                        password_selector = "input[name='password']"
                    
                    console.print("→ Filling password...")
                    await robust_fill(password_selector, password)

                    # Try submitting by pressing Enter key on password field
                    console.print("→ Submitting credentials (Enter key)...")
                    await page.keyboard.press("Enter")
                    
                    # Fallback click on login button
                    submit_selector = "button[type='submit']"
                    if await page.locator(submit_selector).count() == 0:
                        submit_selector = "button:has-text('Masuk'), button:has-text('Log In'), #loginbutton"
                    await robust_click(submit_selector)

                    # Wait for redirect and for network to settle
                    await asyncio.sleep(5)
            except Exception as e:
                console.print(f"[yellow]⚠️ Auto-login failed: {e}. If running locally, please login manually.[/yellow]")

        # Ensure we end up on the watchlist page to trigger the exodus API call
        if "watchlist" not in page.url.lower():
            console.print(f"→ Navigating to watchlist page: {STOCKBIT_URL} ...")
            try:
                await page.goto(STOCKBIT_URL, wait_until="load", timeout=30000)
            except Exception:
                pass

        # We show a beautiful live spinner animation
        max_wait_seconds = 120
        with Live(
            Spinner("dots", text=Text("Listening for Bearer token... Please login or refresh watchlist on browser window", style="bold cyan")),
            refresh_per_second=10
        ) as live:
            for _ in range(max_wait_seconds * 2):
                if token:
                    break
                await asyncio.sleep(0.5)

        # Cleanup page / contexts
        try:
            if browser_choice == "Playwright Chromium":
                await context.close()
            else:
                await page.close()
                await browser.close()
        except Exception:
            pass

        # Stop subprocess if launched
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

        return token


def update_env(token: str) -> bool:
    if not ENV_PATH.exists():
        print(f"✗ .env not found at {ENV_PATH}")
        return False

    with open(ENV_PATH) as f:
        content = f.read()

    # Replace STOCKBIT_BEARER_TOKEN line
    if "STOCKBIT_BEARER_TOKEN=" in content:
        new_content = re.sub(
            r"^STOCKBIT_BEARER_TOKEN=.*$",
            f"STOCKBIT_BEARER_TOKEN={token}",
            content,
            flags=re.MULTILINE,
        )
    else:
        # Append to the end of the file
        new_content = content.rstrip() + f"\nSTOCKBIT_BEARER_TOKEN={token}\n"

    with open(ENV_PATH, "w") as f:
        f.write(new_content)

    print(f"✓ .env updated at {ENV_PATH}")
    return True


def verify_token(token: str) -> bool:
    """Quick decode JWT header and payload to verify it looks valid."""
    try:
        import base64
        import datetime

        parts = token.split(".")
        if len(parts) != 3:
            return False

        header_b64 = parts[0]
        payload_b64 = parts[1]

        def decode_part(part: str) -> dict:
            padding = 4 - len(part) % 4
            if padding != 4:
                part += "=" * padding
            return json.loads(base64.urlsafe_b64decode(part))

        header = decode_part(header_b64)
        payload = decode_part(payload_b64)

        print(f"  JWT Algorithm: {header.get('alg', '?')}")
        print(f"  JWT Issuer:    {payload.get('iss', '?')}")
        
        # User details if present
        data = payload.get("data", {})
        if isinstance(data, dict):
            username = data.get("use") or data.get("username")
            email = data.get("ema") or data.get("email")
            if username:
                print(f"  Stockbit User: {username} ({email or 'no email'})")
        
        # Expiration
        exp = payload.get("exp")
        if exp:
            exp_date = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc)
            print(f"  Expires:       {exp_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
        return True
    except Exception:
        return True  # non-critical, pass


async def main():
    console = Console()
    console.print(Panel(
        "[bold green]📈 Stockbit Token Refresher[/bold green]\n\n"
        "This script intercepts the authorization token from stockbit.com\n"
        "and updates your .env file to enable the realtime sync service.\n\n"
        "[dim]* Note: To reuse your existing logged-in session, choose option 1 or 2 (Default Profile).[/dim]",
        title="[bold white]IDX Realtime Feed Setup[/bold white]",
        border_style="green"
    ))

    # Detect installed browsers
    installed = get_installed_browsers()
    options = []
    
    # Options for connecting/launching primary browser profiles (preserves existing logins)
    options.append("Use existing running browser (port 9222)")
    for name in installed:
        options.append(f"Relaunch {name} with Debugging (Uses your default profile/login)")
        
    # Options for isolated debug profiles
    for name in installed:
        options.append(f"Auto-launch {name} (Isolated Debug Profile - requires login)")
        
    # Option for playwright chromium
    options.append("Launch Playwright Chromium (Standard - requires login)")
    
    options.append("Exit")

    # Display selection menu
    console.print("\n[bold]Select browser option to capture the token:[/bold]")
    for i, opt in enumerate(options, 1):
        console.print(f"  [bold cyan]{i}[/bold cyan]. {opt}")

    choice_str = Prompt.ask("\nEnter choice", choices=[str(x) for x in range(1, len(options) + 1)], default="1")
    choice_idx = int(choice_str) - 1
    selected_option = options[choice_idx]

    if selected_option == "Exit":
        console.print("[yellow]Exiting token refresher.[/yellow]")
        sys.exit(0)

    browser_choice = ""
    browser_path = None

    # Handle using the existing/default profile with debugging
    if selected_option == "Use existing running browser (port 9222)":
        browser_choice = "Connect to existing running browser (port 9222)"
        if not is_port_open(CDP_PORT):
            console.print(f"\n[red]✗ Port {CDP_PORT} is not open.[/red]")
            console.print("[yellow]To use this option, you must run your browser with debugging enabled.[/yellow]")
            console.print("Example command:")
            console.print("  [bold]/Applications/Brave\\ Browser.app/Contents/MacOS/Brave\\ Browser --remote-debugging-port=9222[/bold]")
            sys.exit(1)
            
    elif "Relaunch" in selected_option and "default profile/login" in selected_option:
        # User wants to restart their installed Brave/Chrome/Edge with debugging enabled (Default profile)
        name = selected_option.split("Relaunch ")[1].split(" with Debugging")[0]
        browser_path = installed[name]
        browser_choice = "Connect to existing running browser (port 9222)"
        
        console.print(f"\n[yellow]⚠️ To launch {name} with debugging using your default profile:[/yellow]")
        console.print(f"1. [bold red]Quit {name} completely[/bold red] (Press [bold]Cmd+Q[/bold] inside the browser, or right-click the icon in the Dock and select [bold]Quit[/bold]).")
        console.print("   [dim]* Note: On macOS, clicking the red window 'x' button does NOT close the app; it still runs in the background.[/dim]")
        
        confirm_launch = Confirm.ask(f"2. Have you quit {name} completely and want the script to launch it now?", default=True)
        if confirm_launch:
            console.print(f"→ Launching {name} with remote debugging on port {CDP_PORT}...")
            # We launch WITHOUT --user-data-dir so it opens the user's primary/default profile with their login cookies!
            subprocess.Popen([browser_path, f"--remote-debugging-port={CDP_PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait for port to open
            success = False
            for _ in range(15):
                if is_port_open(CDP_PORT):
                    success = True
                    break
                await asyncio.sleep(0.5)
                
            if not success:
                console.print(f"\n[red]✗ Port {CDP_PORT} did not open.[/red]")
                console.print(f"[yellow]This means {name} is likely still running in the background and locking the profile.[/yellow]")
                console.print(f"Please make sure {name} is fully closed before running this script.")
                sys.exit(1)
            console.print(f"[green]✓ {name} launched successfully with your default profile.[/green]")
        else:
            console.print(f"\nPlease run this command manually in terminal to open it:")
            console.print(f"  [bold cyan]\"{browser_path}\" --remote-debugging-port={CDP_PORT}[/bold cyan]")
            console.print("Then run this script again.")
            sys.exit(1)
            
    elif "Isolated Debug Profile" in selected_option:
        name = selected_option.split("Auto-launch ")[1].split(" (Isolated")[0]
        browser_choice = name
        browser_path = installed[name]
        
    elif selected_option == "Launch Playwright Chromium (Standard - requires login)":
        browser_choice = "Playwright Chromium"

    token = await refresh_token(browser_choice, browser_path)

    if not token:
        console.print("\n[red]✗ Failed to capture token.[/red]")
        console.print("Make sure you are logged in to Stockbit and your internet connection is active.")
        sys.exit(1)

    console.print(f"\n[green]✓ Token captured successfully![/green]")
    console.print(f"  Token preview: [dim]{token[:32]}...{token[-8:]}[/dim]")
    verify_token(token)

    if update_env(token):
        console.print("\n[bold green]✔ .env file updated successfully![/bold green]")
        
        # Ask to run the main script
        run_main = Confirm.ask("\nDo you want to run the main script (main.py) now?", default=True)
        if run_main:
            console.print("\n[bold green]🚀 Starting idx-realtime-feed main.py...[/bold green]\n")
            try:
                subprocess.run([sys.executable, "main.py"])
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped main.py.[/yellow]")
    else:
        console.print("\n[red]✗ Failed to update .env. Please update it manually:[/red]")
        console.print(f"  STOCKBIT_BEARER_TOKEN={token}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[yellow]Cancelled by user.[/yellow]")
        sys.exit(0)

