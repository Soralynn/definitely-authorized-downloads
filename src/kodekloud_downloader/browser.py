"""Manual browser sign-in, with optional explicit debugging-session support."""

import getpass
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def manual_browser_signin(browser_name, executable_path=None):
    executable = (
        Path(executable_path) if executable_path else browser_path(browser_name)
    )
    if executable is None or not executable.is_file():
        raise RuntimeError(
            f"Cannot find {browser_name}. Install it or use --browser-path."
        )
    subprocess.Popen(
        [str(executable), "https://learn.kodekloud.com/user/courses"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(
        "Sign in and complete verification in your normal browser.\n"
        "After the courses page loads, press F12 and open:\n"
        "Application > Storage > Cookies > https://learn.kodekloud.com\n"
        "Find session-cookie and copy its Value.\n"
        "Paste it at the hidden prompt below, then press Enter.\n"
        "It is used only for this run; do not send it in chat."
    )
    try:
        token = getpass.getpass("Session value (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Sign-in cancelled.") from None
    if not token:
        raise RuntimeError("No session value provided. Sign in and try again.")
    return token


def browser_path(name: str = "brave") -> Optional[Path]:
    """Locate an installed browser without accessing its personal profile."""
    if name not in ("brave", "chrome"):
        raise ValueError("Browser must be brave or chrome")
    system = platform.system()
    if system == "Windows":
        relative = (
            Path("BraveSoftware/Brave-Browser/Application/brave.exe")
            if name == "brave"
            else Path("Google/Chrome/Application/chrome.exe")
        )
        candidates = [
            Path(os.environ[root]) / relative
            for root in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")
            if os.environ.get(root)
        ]
    elif system == "Darwin":
        app = "Brave Browser" if name == "brave" else "Google Chrome"
        candidates = [Path(f"/Applications/{app}.app/Contents/MacOS/{app}")]
    else:
        binaries = (
            ("brave-browser", "brave")
            if name == "brave"
            else ("google-chrome", "chromium", "chromium-browser")
        )
        candidates = [Path("/usr/bin") / binary for binary in binaries]
    return next((path for path in candidates if path.is_file()), None)


def _chrome_default_path() -> Optional[Path]:
    return browser_path("chrome")


def _extract_session_cookie(context) -> Optional[str]:
    for cookie in context.cookies("https://learn.kodekloud.com"):
        domain = cookie.get("domain", "").lstrip(".")
        if cookie["name"] == "session-cookie" and (
            domain == "kodekloud.com" or domain.endswith(".kodekloud.com")
        ):
            return cookie["value"]
    return None


def get_session_token_from_browser(
    port: Optional[int] = None,
    auto_launch: bool = False,
    browser_name: str = "brave",
    executable_path: Optional[str] = None,
) -> Optional[str]:
    """Wait up to five minutes for local sign-in; never print the token.

    Auto-launch opens a normal browser and asks for a manually supplied token.
    Explicit non-auto-launch mode can
    connect to an existing browser's localhost debugging port.
    """
    if auto_launch:
        return manual_browser_signin(browser_name, executable_path)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Install browser support: uv sync --extra browser") from None

    with sync_playwright() as pw:
        attached_browser = None
        port = port or int(os.environ.get("KODEKLOUD_CDP_PORT", "9222"))
        attached_browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = attached_browser.contexts[0]
        try:
            token = _extract_session_cookie(context)
            if token:
                return token
            page = context.new_page()
            page.goto(
                "https://learn.kodekloud.com/user/courses",
                wait_until="domcontentloaded",
            )
            print(
                f"Sign in to KodeKloud in {browser_name.title()}. "
                "Waiting up to 5 minutes..."
            )
            for _ in range(300):
                token = _extract_session_cookie(context)
                if token:
                    logger.info("KodeKloud sign-in completed")
                    return token
                page.wait_for_timeout(1000)
            raise RuntimeError("Sign-in timed out. Run the command again to retry.")
        finally:
            if attached_browser is None:
                context.close()
