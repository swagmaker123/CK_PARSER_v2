from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from config.sources import kommersant as cfg


async def collect_one_day(date_str, log_fn=None):
    def log(level, msg, *args):
        if log_fn:
            log_fn(level, msg, *args)

    start_url = cfg.ARCHIVE_URL.format(date=date_str)
    all_items = []
    seen_urls = set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=cfg.PLAYWRIGHT_ARGS,
        )
        page = await browser.new_page()

        try:
            log("info", "[%s] Открываю архив: %s", date_str, start_url)
            await page.goto(
                start_url,
                wait_until="domcontentloaded",
                timeout=cfg.PAGE_GOTO_TIMEOUT,
            )
            await page.wait_for_timeout(cfg.PAGE_WAIT_MS)

            page_num = 1
            empty_streak = 0

            while True:
                items = await page.evaluate(cfg.JS_COLLECT)
                new_count = 0

                for item in items:
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        all_items.append(item)
                        new_count += 1

                log(
                    "info",
                    "[%s] стр.%s: +%s новых (всего: %s)",
                    date_str,
                    page_num,
                    new_count,
                    len(all_items),
                )

                if new_count == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0

                if empty_streak >= cfg.EMPTY_STREAK_LIMIT:
                    log(
                        "info",
                        "[%s] 2 пустые страницы подряд — день собран",
                        date_str,
                    )
                    break

                btn_found = False
                btn = page.locator(cfg.SEL_MORE)

                for _ in range(cfg.SCROLL_ATTEMPTS):
                    await page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                    await page.wait_for_timeout(cfg.SCROLL_WAIT_MS)
                    try:
                        await btn.wait_for(
                            state="visible",
                            timeout=cfg.BUTTON_WAIT_MS,
                        )
                        btn_found = True
                        break
                    except PlaywrightTimeout:
                        pass

                if not btn_found:
                    log("info", "[%s] Кнопки нет — день собран", date_str)
                    break

                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(cfg.BEFORE_CLICK_WAIT_MS)

                log(
                    "info",
                    "[%s] Клик 'Показать еще' (стр.%s -> %s)",
                    date_str,
                    page_num,
                    page_num + 1,
                )

                current_url = page.url
                try:
                    await btn.click(timeout=cfg.CLICK_TIMEOUT)
                except PlaywrightTimeout:
                    log("info", "[%s] Кнопка не кликается — конец дня", date_str)
                    break

                for _ in range(cfg.AFTER_CLICK_POLLS):
                    await page.wait_for_timeout(cfg.AFTER_CLICK_WAIT_MS)
                    if page.url != current_url:
                        break

                page_num += 1

        except Exception as e:
            log("error", "[%s] Playwright: %s", date_str, e)
        finally:
            await page.close()
            await browser.close()

    log("info", "[%s] Ссылок собрано: %s", date_str, len(all_items))
    return all_items
