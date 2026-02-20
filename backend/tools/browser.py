import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ScreenshotResult:
    route: str
    path: str | None
    status: str  # captured, failed, skipped
    error: str | None = None


def _slugify(route: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "_", route.strip("/"))
    return slug or "root"


async def _wait_for_port(port: int, timeout: int = 30) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.5)
    return False


async def capture_screenshots(
    workspace: Path,
    start_cmd: str,
    routes: list[str],
    port: int = 3000,
    timeout: int = 30,
    artifacts_dir: Path | None = None,
) -> list[dict]:
    artifacts_dir = artifacts_dir or Path("./artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    # Start dev server
    process = await asyncio.create_subprocess_shell(
        start_cmd,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        # Wait for server
        server_ready = await _wait_for_port(port, timeout=timeout)
        if not server_ready:
            process.kill()
            return [
                {"route": r, "path": None, "status": "failed", "error": "Server did not start"}
                for r in routes
            ]

        # Capture screenshots with Playwright
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})

            for route in routes:
                url = f"http://localhost:{port}{route}"
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{_slugify(route)}_{ts}.png"
                filepath = str(artifacts_dir / filename)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                    await page.screenshot(path=filepath, full_page=True)
                    results.append({
                        "route": route,
                        "path": filepath,
                        "status": "captured",
                    })
                    logger.info("Screenshot captured: %s -> %s", route, filepath)
                except Exception as exc:
                    logger.warning("Screenshot failed for %s: %s", route, exc)
                    results.append({
                        "route": route,
                        "path": None,
                        "status": "failed",
                        "error": str(exc),
                    })

            await browser.close()

    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()

    return results
