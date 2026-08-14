import asyncio
import json

from playwright.async_api import async_playwright


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1366, "height": 768})
        await page.goto("http://127.0.0.1:8083/", wait_until="domcontentloaded")
        result = await page.evaluate(
            """() => {
              const main = document.querySelector('#tab-eventista');
              const list = document.querySelector('#tab-eventista .card-jobs .job-list');
              if (!main || !list) return { error: 'Eventista DOM not found' };
              main.classList.add('active');
              const style = getComputedStyle(list);
              return {
                asset: [...document.scripts].find(s => s.src.includes('eventista.js'))?.src || '',
                overflowY: style.overflowY,
                clientHeight: list.clientHeight,
                scrollHeight: list.scrollHeight,
                scrollbarGutter: style.scrollbarGutter,
              };
            }"""
        )
        print(json.dumps(result))
        await browser.close()
        return 1 if result.get("error") or result.get("overflowY") != "scroll" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
