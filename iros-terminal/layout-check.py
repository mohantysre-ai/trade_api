from playwright.sync_api import sync_playwright

URL = 'http://localhost:3000'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    page.goto(URL, wait_until='networkidle')
    page.click('[aria-label="Desk views"] >> text=INDEX OPTIONS')
    page.wait_for_timeout(2000)

    def inspect(width, label):
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(1000)
        grid = page.locator('.ix-radar > div').filter(
            has_text='PORTFOLIO RISK GOVERNOR'
        ).filter(
            has_text='NO-TRADE BENCHMARK'
        ).filter(
            has_text='MARKET DECISION'
        )
        if grid.count() == 0:
            print(f'[{label}] summary grid not found')
            return
        classes = grid.first.get_attribute('class')
        style = grid.first.evaluate('el => { const s = getComputedStyle(el); return { display: s.display, gridTemplateColumns: s.gridTemplateColumns, width: el.offsetWidth }; }')
        print(f'[{label}] classes={classes}')
        print(f'[{label}] style={style}')

    inspect(1280, 'DESKTOP')
    inspect(1024, 'TABLET')
    inspect(768, 'SMALL-TABLET')
    inspect(520, 'BOUNDARY')
    inspect(468, 'NARROW')
    inspect(390, 'SMALL-MOBILE')

    page.screenshot(path='D:/trade_api/iros-terminal/layout-check.png', full_page=True)
    browser.close()
