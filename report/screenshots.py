"""Скриншоты дашборда по разделам (каждый вопрос — отдельная картинка) для отчёта и презентации.

Нужен запущенный дашборд и Playwright с установленным Chrome:
    pip install playwright
    python report/screenshots.py http://localhost:8501
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
OUT = Path(__file__).parent / "img"
OUT.mkdir(exist_ok=True)
PAGES = {"forecast": "", "weather": "weather", "data": "data", "ops": "ops"}

# Позиции блоков страницы: заголовок страницы и все заголовки-вопросы (h4). Блоки на одной высоте
# (две колонки) объединяются. Возвращает [(top, bottom)] в координатах страницы.
JS = """() => {
  const main = document.querySelector('[data-testid="stMainBlockContainer"]');
  const box = main.getBoundingClientRect();
  const heads = [...main.querySelectorAll('h1, h4')].map(h => h.getBoundingClientRect().top);
  const rules = [...main.querySelectorAll('hr')].map(h => h.getBoundingClientRect().top);
  const blocks = [...main.querySelectorAll('[data-testid="stElementContainer"]')]
        .map(e => e.getBoundingClientRect()).filter(r => r.height > 0);
  const bottom = Math.max(...blocks.map(r => r.bottom));
  return {left: box.left, right: box.right, heads, rules, bottom};
}"""


def shoot(page, name):
    page.wait_for_selector("[data-testid='stMainBlockContainer']", timeout=60000)
    time.sleep(4)
    for _ in range(90):
        if page.locator("[data-testid='stSpinner'], [data-testid='stSkeleton'], [data-testid='stStatusWidget']").count() == 0:
            break
        time.sleep(1)
    time.sleep(3)
    g = page.evaluate(JS)
    tops = []
    for t in sorted(g["heads"]):
        if not tops or t - tops[-1] > 40:  # заголовки двух колонок на одной высоте — один блок
            tops.append(t)
    edges = tops + [g["bottom"] + 10]
    for i, (a, b) in enumerate(zip(edges, edges[1:])):
        # блок заканчивается на ближайшем разделителе (st.divider), если он раньше следующего заголовка
        b = min([b] + [r for r in g["rules"] if a + 40 < r < b])
        clip = {"x": g["left"] + 40, "y": a - 12, "width": g["right"] - g["left"] - 80, "height": b - a}
        page.screenshot(path=str(OUT / f"{name}_{i}.png"), clip=clip)
        print(f"{name}_{i}.png", round(clip["height"]))


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    pg = browser.new_page(viewport={"width": 1500, "height": 4000}, device_scale_factor=1.5, color_scheme="light")
    for name, path in PAGES.items():
        pg.goto(f"{URL}/{path}")
        shoot(pg, name)
    browser.close()
