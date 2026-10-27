"""The README's demo GIF and screenshot, recorded from the running app with a headless browser.

    uv run --with playwright --with pillow python scripts/capture_demo.py [--url URL]

Needs a running server (`uv run poe dev`, or `docker compose up`) with the demo users, and a
Chromium-based browser: the installed Edge or Chrome (`--channel`), or Playwright's own
(`playwright install chromium`, then `--channel ""`). The demo password comes from the .env
(FINQL_DEMO_PASSWORD). Playwright and Pillow are not project dependencies: `--with` brings
them for this one run.
"""

import argparse
import io
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

from finql.core.config import get_settings

OUT_DIR = Path("docs/img")
WIDTH, HEIGHT = 1200, 860
GIF_WIDTH = 900
QUESTION = "Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?"


class Recorder:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[tuple[Image.Image, int]] = []

    def frame(self, hold_ms: int = 120) -> None:
        image = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        height = round(image.height * GIF_WIDTH / image.width)
        self.frames.append((image.resize((GIF_WIDTH, height), Image.Resampling.LANCZOS), hold_ms))

    def save_gif(self, path: Path) -> None:
        # One palette for all frames: smaller file, and no flicker between frames.
        first = self.frames[0][0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames = [
            image.quantize(palette=first, dither=Image.Dither.NONE) for image, _ in self.frames
        ]
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=[hold for _, hold in self.frames],
            loop=0,
            optimize=True,
        )


def type_slowly(recorder: Recorder, selector: str, text: str, every: int = 6) -> None:
    field = recorder.page.locator(selector)
    for start in range(0, len(text), every):
        field.press_sequentially(text[start : start + every])
        recorder.frame(60)


def record(url: str, channel: str | None, password: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel or None)
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            locale="hu-HU",
            color_scheme="light",
        )
        recorder = Recorder(page)

        page.goto(url)
        page.wait_for_selector("#login-view:not([hidden])")
        recorder.frame(1200)
        page.get_by_role("button", name="pecs@minta-bank.example").click()
        type_slowly(recorder, "input[name=password]", password, every=4)
        page.locator("#login-form button[type=submit]").click()
        page.wait_for_selector("#chat-view:not([hidden])")
        recorder.frame(1200)

        type_slowly(recorder, "#question", QUESTION)
        recorder.frame(500)
        page.locator("#send").click()
        deadline = time.monotonic() + 60
        while not page.locator(".answer").count():
            if time.monotonic() > deadline:
                raise TimeoutError("no answer within 60 s")
            recorder.frame(150)
        recorder.frame(2500)

        # The SQL and the result table of the data tool, then the first quoted source.
        page.locator(".tool summary").first.click()
        page.locator(".messages").evaluate("node => node.scrollTo(0, node.scrollHeight)")
        recorder.frame(3000)
        page.locator(".tool summary").first.click()
        page.locator(".citations summary").first.click()
        page.locator(".messages").evaluate("node => node.scrollTo(0, node.scrollHeight)")
        recorder.frame(3500)

        page.locator(".tool summary").first.click()
        page.screenshot(path=OUT_DIR / "chat.png")
        browser.close()

    recorder.save_gif(OUT_DIR / "demo.gif")
    size = (OUT_DIR / "demo.gif").stat().st_size
    print(f"{len(recorder.frames)} képkocka, demo.gif: {size / 1024:.0f} KB, chat.png kész")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000/")
    parser.add_argument("--channel", default="msedge", help='msedge, chrome, or "" (bundled)')
    args = parser.parse_args()
    password = get_settings().demo_password
    if password is None:
        raise SystemExit("Hiányzik a FINQL_DEMO_PASSWORD.")
    record(args.url, args.channel, password.get_secret_value())


if __name__ == "__main__":
    main()
