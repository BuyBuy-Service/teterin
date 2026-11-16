"""Сборка презентации .pptx для защиты.   python report/build_deck.py
Графики — нативные диаграммы PowerPoint (редактируются), экраны дашборда — скриншоты (report/screenshots.py).
В заметках к каждому слайду — кто рассказывает и что говорить."""
import sqlite3

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from common import ROOT, config, facts, fmt, trimmed

OUT = ROOT / "report" / "Презентация_AeroPulse.pptx"
F = facts()
md, mf = F["metrics"]["dep_del15_share"], F["metrics"]["dep_flown"]

# палитра: ночное небо + небесно-голубой + оранжевый «задержка»
NAVY, NAVY2 = RGBColor(0x0B, 0x1F, 0x3A), RGBColor(0x16, 0x33, 0x5C)
SKY, SKY_L = RGBColor(0x2A, 0x78, 0xD6), RGBColor(0xE6, 0xF0, 0xFB)
ORANGE = RGBColor(0xEB, 0x68, 0x34)
INK, INK2, MUTED = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x45, 0x4A, 0x55), RGBColor(0x89, 0x87, 0x81)
WHITE, CARD = RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xF3, 0xF6, 0xFA)
GRID = RGBColor(0xE1, 0xE0, 0xD9)
HEAD, BODY = "Cambria", "Calibri"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5
N = [0]


def bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, font=BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, name=None, spacing=None):
    """runs: строка, или список абзацев; абзац — строка или список (текст, {опции})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        for t, o in (para if isinstance(para, list) else [(para, {})]):
            r = p.add_run()
            r.text = t
            r.font.name = o.get("font", font)
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", False)
            r.font.color.rgb = o.get("color", color)
    return tb


def box(slide, x, y, w, h, fill, line=None, radius=True, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shp.adjustments[0] = 0.08
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    if name:
        shp.name = name
    return shp


def circle_num(slide, x, y, d, label, fill=SKY, color=WHITE, size=16):
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid()
    c.fill.fore_color.rgb = fill
    c.line.fill.background()
    c.shadow.inherit = False
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), True, color, BODY


def content_slide(title, speaker, notes, kicker=None):
    s = prs.slides.add_slide(BLANK)
    N[0] += 1
    bg(s, WHITE)
    if kicker:
        text(s, 0.6, 0.38, 9, 0.3, kicker.upper(), size=11, color=SKY, bold=True, name="Kicker")
    text(s, 0.6, 0.62, 12.1, 0.8, title, size=30, bold=True, font=HEAD, color=NAVY, name="Title")
    text(s, 0.6, 7.0, 8, 0.3, f"AeroPulse · {config.AIRPORT_IATA} · {speaker}", size=10, color=MUTED, name="Footer")
    text(s, 12.2, 7.0, 0.55, 0.3, str(N[0]), size=10, color=MUTED, align=PP_ALIGN.RIGHT, name="SlideNumber")
    s.notes_slide.notes_text_frame.text = f"Говорит: {speaker}.\n{notes}"
    return s


def picture(slide, name, x, y, w=None, h=None):
    path = trimmed(name)
    iw, ih = Image.open(path).size
    if w and h:  # вписать в рамку с сохранением пропорций
        k = min(w / iw, h / ih)
        pw, ph = iw * k, ih * k
        x, y = x + (w - pw) / 2, y + (h - ph) / 2
    elif w:
        pw, ph = w, w * ih / iw
    else:
        pw, ph = h * iw / ih, h
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(pw), Inches(ph))
    pic.line.color.rgb = GRID
    pic.line.width = Pt(0.75)
    return pic


def style_chart(chart, legend=False, pct=True, size=12):
    chart.font.size = Pt(size)
    chart.font.name = BODY
    chart.font.color.rgb = INK2
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
    va = chart.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = GRID
    va.format.line.fill.background()
    va.tick_labels.font.color.rgb = MUTED
    if pct:
        va.tick_labels.number_format = '0%'
        va.tick_labels.number_format_is_linked = False
    ca = chart.category_axis
    ca.format.line.color.rgb = GRID
    ca.tick_labels.font.color.rgb = INK2
    ca.has_major_gridlines = False


# ======================= 1. Титул =======================
s = prs.slides.add_slide(BLANK)
N[0] += 1
bg(s, NAVY)
text(s, 0.8, 0.7, 11, 0.4, "НИТУ МИСИС · Проектная работа по дисциплине «Визуализация данных»", size=14, color=SKY_L)
text(s, 0.8, 2.0, 11.5, 1.2, "AeroPulse", size=60, bold=True, font=HEAD, color=WHITE, name="Title")
text(s, 0.8, 3.1, 11.5, 1.2, "Прогнозно-аналитическая система мониторинга задержек рейсов аэропорта "
     "Chicago O’Hare (ORD)", size=24, color=SKY_L)
text(s, 0.8, 5.3, 8, 1.0, [[("Селиванова А.К. · Козлов В.Н. · Харлашкина А.В.", {"bold": True})],
                          "группа МПИ-25-4 · преподаватель Тетерин Н.А."], size=16, color=WHITE, spacing=4)
text(s, 0.8, 6.7, 6, 0.4, "Москва, 2026", size=12, color=MUTED)
for i, (v, l) in enumerate([("3", "источника"), ("1,34 млн", "рейсов"), ("7 дней", "прогноз")]):
    box(s, 9.0 + i * 1.4, 5.25, 1.25, 1.05, NAVY2)
    text(s, 9.0 + i * 1.4, 5.35, 1.25, 0.5, v, size=20 if len(v) < 5 else 15, bold=True, color=WHITE,
         align=PP_ALIGN.CENTER)
    text(s, 9.0 + i * 1.4, 5.85, 1.25, 0.3, l, size=11, color=SKY_L, align=PP_ALIGN.CENTER)
s.notes_slide.notes_text_frame.text = (
    "Говорит: Селиванова А.К.\nПредставиться всей командой. Тема №7 «Гражданская авиация»: прогнозируем число "
    "рейсов и долю задержек в аэропорту. Порядок выступления: Селиванова — задача и погода (слайды 2–6), "
    "Харлашкина — данные и надёжность (7–9), Козлов — прогноз и живое демо (10–12).")

# ======================= 2. Задача =======================
s = content_slide("Кому и зачем нужна система", "Селиванова А.К.",
                  "Пользователь — операционный менеджер аэропорта или авиакомпании. Его решение — нужен ли резерв "
                  "персонала, экипажей и стоек на ближайшие дни. Погода прогнозируема на неделю, значит и задержки "
                  "можно предвидеть. Почему США: в РФ статистика задержек не публикуется.", "Постановка задачи")
text(s, 0.6, 1.6, 6.3, 3.5, [
    [("Пользователь", {"bold": True, "color": NAVY})],
    "Операционный менеджер аэропорта или авиакомпании",
    [("Решение", {"bold": True, "color": NAVY})],
    "Нужен ли на ближайшие дни резерв персонала, экипажей и стоек регистрации",
    [("Почему ORD, а не российский аэропорт", {"bold": True, "color": NAVY})],
    "В России статистика пунктуальности не публикуется. Минтранс США раскрывает данные о каждом рейсе",
], size=17, color=INK2, spacing=8)
stats = [(fmt(F["avg_flown"]), "вылетов в сутки", SKY), (f"{F['del15'] * 100:.0f}%", "вылетов задержаны ≥ 15 мин", ORANGE),
         ("2–3 мес.", "лаг публикации факта о задержках", NAVY)]
for i, (v, l, c) in enumerate(stats):
    y = 1.65 + i * 1.7
    box(s, 7.5, y, 5.2, 1.45, CARD)
    text(s, 7.8, y + 0.15, 4.8, 0.8, v, size=40, bold=True, color=c, font=HEAD)
    text(s, 7.8, y + 0.95, 4.8, 0.4, l, size=14, color=INK2)

# ======================= 3. Источники =======================
s = content_slide("Три разнородных источника данных", "Селиванова А.К.",
                  "Разнородность — по способу получения и формату: пакетные ZIP, текст, JSON API. "
                  "Слабоструктурированный источник — METAR: это текст фиксированного формата с показаниями датчиков. "
                  "Все источники проверили реальными запросами до начала разработки.", "Данные")
src = [("BTS On-Time Performance", "Бюро транспортной статистики США",
        ["ZIP с CSV, раз в месяц", "Каждый рейс: план и факт, задержка, отмена, причины",
         f"{fmt(F['flights'])} рейсов ORD за 24 мес."], "структурированные"),
       ("METAR · Iowa Mesonet", "Метеостанция аэропорта",
        ["Текстовые сводки, каждый час", "Ветер, видимость, облачность, явления",
         f"{fmt(F['metar'])} сводок"], "слабоструктурированные"),
       ("Open-Meteo", "Прогноз погоды",
        ["JSON API", "Почасовой прогноз на 7 суток", "Осадки, снег, порывы, видимость"], "структурированные")]
for i, (t, sub, items, kind) in enumerate(src):
    x = 0.6 + i * 4.1
    box(s, x, 1.65, 3.85, 3.6, CARD)
    circle_num(s, x + 0.3, 1.9, 0.55, str(i + 1), fill=ORANGE if i == 1 else SKY)
    text(s, x + 1.0, 1.9, 2.7, 0.6, t, size=17, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, 2.65, 3.3, 0.35, sub, size=12, color=MUTED)
    text(s, x + 0.3, 3.05, 3.3, 1.7, ["— " + it for it in items], size=14, color=INK2, spacing=6)
    text(s, x + 0.3, 4.8, 3.3, 0.3, kind, size=12, bold=True, color=ORANGE if i == 1 else SKY)
box(s, 0.6, 5.55, 12.1, 1.15, NAVY)
text(s, 0.9, 5.65, 11.5, 0.35, "Так выглядит METAR:", size=12, color=SKY_L)
text(s, 0.9, 6.0, 11.5, 0.5, "KORD 161451Z 27015G25KT 3SM -SN BR OVC008 M02/M04 A2990", size=22, bold=True,
     color=WHITE, font="Courier New")

# ======================= 4. METAR -> признаки =======================
s = content_slide("Из текста сводки — в признаки", "Селиванова А.К.",
                  "Числовые группы разбирает библиотека metar, погодные явления — наш собственный разбор токенов "
                  "(явления «в окрестности» VC и примечания RMK не учитываем). Категория полётных условий — по "
                  "правилам FAA. Из 23,6 тыс. сводок не разобрана одна — битая автоматическая. Потом каждый вылет "
                  "сопоставляем с последней сводкой не старше 90 минут до вылета.", "Слабоструктурированные данные")
parts = [("KORD", "аэропорт"), ("161451Z", "16-е, 14:51 UTC"), ("27015G25KT", "ветер 15 уз,\nпорывы 25"),
         ("3SM", "видимость\n3 мили"), ("-SN BR", "слабый снег,\nдымка"), ("OVC008", "облака\n800 футов"),
         ("M02/M04", "−2 °C,\nточка росы −4")]
x = 0.6
for tok, mean in parts:
    w = 0.42 + 0.17 * len(tok)
    box(s, x, 1.75, w, 0.75, SKY if tok in ("27015G25KT", "3SM", "-SN BR", "OVC008") else NAVY2)
    text(s, x, 1.75, w, 0.75, tok, size=17, bold=True, color=WHITE, font="Courier New", align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE)
    text(s, x, 2.6, w, 0.7, mean.split("\n"), size=12, color=INK2, align=PP_ALIGN.CENTER)
    x += w + 0.12
cats = [("VFR", "> 5 миль и > 3000 футов", RGBColor(0x9E, 0xC5, 0xF4)), ("MVFR", "3–5 миль или 1000–3000", RGBColor(0x55, 0x98, 0xE7)),
        ("IFR", "1–3 мили или 500–1000", RGBColor(0x25, 0x6A, 0xBF)), ("LIFR", "< 1 мили или < 500 футов", RGBColor(0x10, 0x42, 0x81))]
text(s, 0.6, 3.75, 7, 0.4, "Категория полётных условий (FAA)", size=16, bold=True, color=NAVY)
for i, (c, d, col) in enumerate(cats):
    xx = 0.6 + i * 3.05
    box(s, xx, 4.25, 2.9, 1.05, col)
    text(s, xx + 0.2, 4.3, 2.5, 0.5, c, size=20, bold=True, color=WHITE if i else NAVY)
    text(s, xx + 0.2, 4.8, 2.6, 0.4, d, size=12, color=WHITE if i else NAVY)
box(s, 0.6, 5.6, 12.1, 1.1, CARD)
text(s, 0.9, 5.7, 11.6, 0.9, [
    [(f"{fmt(F['metar_ok'])} из {fmt(F['metar'])} ", {"bold": True, "color": NAVY}),
     ("сводок разобраны. Каждый вылет сопоставлен с последней сводкой не старше 90 минут до планового вылета — "
      "так погода связывается с конкретным рейсом.", {})]], size=15, color=INK2, anchor=MSO_ANCHOR.MIDDLE)

# ======================= 5. Погода и задержки (график) =======================
s = content_slide("Гроза утраивает долю задержек", "Селиванова А.К.",
                  "Это главный аналитический результат по погоде. Для каждого вылета взяли погоду в момент вылета. "
                  "Без опасных явлений задержано 23%, при грозе — 67%. Вывод для менеджера: гроза и ледяной дождь "
                  "в прогнозе — сигнал готовить резерв в первую очередь.", "Погода и задержки")
cd = CategoryChartData()
phen = [("Без явлений", .23), ("Порывы ≥ 30 уз", .34), ("Дождь", .34), ("Туман", .45), ("Снег", .46),
        ("Ледяной дождь", .54), ("Гроза", .67)]
cd.categories = [p[0] for p in phen]
cd.add_series("Доля задержанных вылетов", [p[1] for p in phen])
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.55), Inches(7.6), Inches(5.2), cd)
ch = gf.chart
style_chart(ch)
ch.plots[0].gap_width = 45
ch.plots[0].has_data_labels = True
dl = ch.plots[0].data_labels
dl.number_format, dl.number_format_is_linked, dl.position = '0%', False, XL_LABEL_POSITION.OUTSIDE_END
dl.font.size, dl.font.bold, dl.font.color.rgb = Pt(13), True, INK2
ser = ch.plots[0].series[0]
ser.format.fill.solid()
ser.format.fill.fore_color.rgb = SKY
for idx in (5, 6):
    pt = ser.points[idx]
    pt.format.fill.solid()
    pt.format.fill.fore_color.rgb = ORANGE
ch.value_axis.maximum_scale = 0.8
ch.has_title = True
ch.chart_title.text_frame.text = "Доля вылетов, задержанных ≥ 15 мин, при погоде в момент вылета"
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = INK2
for i, (v, l, c) in enumerate([("67%", "задержано при грозе", ORANGE), ("23%", "без опасных явлений", SKY),
                               ("24 → 34%", "от VFR к IFR", NAVY)]):
    y = 1.7 + i * 1.65
    box(s, 8.7, y, 4.0, 1.4, CARD)
    text(s, 9.0, y + 0.12, 3.6, 0.8, v, size=36, bold=True, color=c, font=HEAD)
    text(s, 9.0, y + 0.9, 3.6, 0.4, l, size=14, color=INK2)

# ======================= 6. Причины и часы =======================
s = content_slide("Задержки копятся к вечеру", "Селиванова А.К.",
                  "По часам: утром задержано около 10% вылетов, к 19–22 часам — до 38%: опоздания передаются по "
                  "цепочке рейсов. Поэтому резерв нужнее вечерним сменам. По причинам: официальная «погода» — лишь 9% "
                  "минут, но обычная непогода записывается в NAS и потом всплывает как «поздний прилёт самолёта».",
                  "Погода и задержки")
con = sqlite3.connect(config.DB_PATH)
hrs = con.execute("""SELECT crs_dep_time/100 h, avg(dep_del15) FROM flights WHERE direction='departure'
                     AND cancelled=0 AND dep_del15 IS NOT NULL AND is_deleted=0 GROUP BY 1 HAVING count(*) > 5000
                     ORDER BY 1""").fetchall()
con.close()
cd = CategoryChartData()
cd.categories = [f"{int(h):02d}" for h, _ in hrs]
cd.add_series("Доля задержанных вылетов", [v for _, v in hrs])
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.55), Inches(7.4), Inches(5.2), cd)
ch = gf.chart
style_chart(ch)
ch.plots[0].gap_width = 40
ser = ch.plots[0].series[0]
ser.format.fill.solid()
ser.format.fill.fore_color.rgb = SKY
for i, (h, v) in enumerate(hrs):
    if v >= 0.35:
        pt = ser.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = ORANGE
ch.has_title = True
ch.chart_title.text_frame.text = "Доля задержанных вылетов по часу вылета (местное время)"
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = INK2
c = F["causes"]
text(s, 8.5, 1.6, 4.2, 0.4, "Минуты задержки по причинам", size=16, bold=True, color=NAVY)
causes = [("Поздний прилёт самолёта", c["late"]), ("Перевозчик", c["carrier"]), ("Авиасистема (NAS)", c["nas"]),
          ("Погода", c["weather"])]
for i, (name, share) in enumerate(causes):
    y = 2.2 + i * 0.95
    text(s, 8.5, y, 3.2, 0.35, name, size=14, color=INK2)
    text(s, 11.7, y, 1.0, 0.35, f"{share * 100:.0f}%", size=14, bold=True, color=NAVY, align=PP_ALIGN.RIGHT)
    box(s, 8.5, y + 0.4, 4.2, 0.22, CARD, radius=False)
    box(s, 8.5, y + 0.4, max(0.05, 4.2 * share / causes[0][1]), 0.22, ORANGE if name == "Погода" else SKY, radius=False)
text(s, 8.5, 6.0, 4.2, 0.8, "Обычная непогода учитывается как NAS и «поздний прилёт», поэтому «погода» занижена.",
     size=12, color=MUTED)

# ======================= 7. Архитектура =======================
s = content_slide("Как устроена обработка", "Харлашкина А.В.",
                  "Слои: сырые данные хранятся как пришли (ZIP-файлы с хэшем, тексты METAR, JSON), затем очищенные "
                  "таблицы, витрина по дням и прогноз. Каждый шаг — «джоба» с единой обвязкой. Ошибка одного шага "
                  "не валит остальные. Запуск — одной командой run.bat или по расписанию через Планировщик Windows. "
                  "Стек: Python, SQLite, Streamlit — без серверов, запускается на любом ноутбуке.", "Архитектура")
picture(s, "ops_1", 0.6, 1.55, w=7.8, h=3.9)
steps = [("raw", "исходные данные как пришли: ZIP + SHA-256, тексты METAR, JSON"),
         ("очищенные", "рейсы, разобранная погода, почасовой прогноз"),
         ("витрина", "день × рейсы × погода — основа дашборда и модели"),
         ("прогноз", "модель, проверка на истории, версии")]
for i, (t, d) in enumerate(steps):
    y = 1.6 + i * 0.98
    circle_num(s, 8.8, y, 0.5, str(i + 1), size=14)
    text(s, 9.45, y - 0.02, 3.3, 0.35, t, size=15, bold=True, color=NAVY)
    text(s, 9.45, y + 0.32, 3.3, 0.6, d, size=12, color=INK2)
box(s, 0.6, 5.75, 12.1, 0.95, CARD)
text(s, 0.9, 5.75, 11.6, 0.95, [[("Стек: ", {"bold": True, "color": NAVY}),
                                 ("Python · SQLite · pandas · scikit-learn · Streamlit + Plotly · Планировщик Windows. "
                                  "Без серверов: вся система запускается одной командой.", {})]],
     size=15, color=INK2, anchor=MSO_ANCHOR.MIDDLE)

# ======================= 8. Надёжность =======================
s = content_slide("Повторный запуск — 0 новых строк", "Харлашкина А.В.",
                  "Четыре требования методички к загрузке. Инкрементальность — watermark по каждому источнику. "
                  "Идемпотентность — upsert по естественным ключам, хэши файлов, данные и watermark в одной "
                  "транзакции. Устойчивость — ретраи с паузой и Retry-After, карантин битых файлов. Журнал — каждая "
                  "строка = запуск. Проверено: первый запуск — 1,34 млн рейсов, повторный — 0. Здесь же можно показать "
                  "демо: режим «лимит запросов (429)» на странице «Журнал и качество».", "Надёжность загрузки")
cards = [("Инкрементальность", "Watermark по каждому источнику: догружаются только новые месяцы BTS и новые сводки "
                               "METAR (с перекрытием 2 ч)"),
         ("Идемпотентность", "Upsert по естественным ключам, хэш файлов и ответов; данные и watermark — в одной "
                             "транзакции"),
         ("Устойчивость", "Таймауты, до 4 попыток с паузой и учётом Retry-After, карантин битых файлов, "
                          "ошибка шага не валит цепочку"),
         ("Журнал загрузок", "Каждый запуск: параметры, статус, новые / обновлённые / пропущенные строки, "
                             "HTTP-запросы, повторы, ошибка")]
for i, (t, d) in enumerate(cards):
    x, y = 0.6 + (i % 2) * 4.0, 1.65 + (i // 2) * 2.55
    box(s, x, y, 3.8, 2.35, CARD)
    circle_num(s, x + 0.3, y + 0.3, 0.5, str(i + 1), size=14)
    text(s, x + 0.95, y + 0.32, 2.7, 0.45, t, size=16, bold=True, color=NAVY)
    text(s, x + 0.3, y + 0.95, 3.25, 1.3, d, size=13, color=INK2)
box(s, 8.75, 1.65, 3.95, 4.9, NAVY)
text(s, 9.05, 1.9, 3.4, 0.4, "Проверка на живых данных", size=14, color=SKY_L)
text(s, 9.05, 2.4, 3.4, 0.9, fmt(F["flights"]), size=34, bold=True, color=WHITE, font=HEAD)
text(s, 9.05, 3.2, 3.4, 0.4, "рейсов — первый запуск, ~33 мин", size=13, color=SKY_L)
text(s, 9.05, 4.0, 3.4, 0.9, "0", size=54, bold=True, color=ORANGE, font=HEAD)
text(s, 9.05, 5.0, 3.4, 0.8, "новых строк при повторном запуске — по всем источникам", size=13, color=SKY_L)
text(s, 0.6, 6.7, 8, 0.3, "Ручные правки помечаются флагом и не перезаписываются при повторной загрузке.",
     size=12, color=MUTED)

# ======================= 9. Качество =======================
s = content_slide("Проверки качества нашли реальные проблемы", "Харлашкина А.В.",
                  "14 правил, запускаются после каждой загрузки, результаты — на дашборде с примерами записей. "
                  "Ошибки уровня error не найдены. Предупреждения — реальные особенности: сверхдолгие задержки "
                  "(данные верные, поэтому правило понизили до warning), отменённые рейсы с временем вылета — "
                  "самолёт вылетел и вернулся, праздничные провалы объёма, битая сводка METAR.", "Контроль качества")
rows = [("Правило", "Проверено", "Нарушений", "Что это"),
        ("Задержка вне −60…2000 мин", "1 310 479", "26", "реальные задержки > 33 ч"),
        ("Отменённый рейс со временем вылета", "28 117", "1 568", "вылетел и вернулся"),
        ("Объём вылетов вне ±3σ", "730 дней", "7", "праздники: День благодарения, 4 июля"),
        ("Перерыв в METAR > 2 ч", "23 588", "3", "пропуски наблюдений"),
        ("METAR не разобран", "23 588", "1", "битая автоматическая сводка"),
        ("DepDel15 ≠ минутам задержки", "1 310 479", "0", "согласовано"),
        ("Погода вне физических диапазонов", "23 587", "0", "—")]
tbl = s.shapes.add_table(len(rows), 4, Inches(0.6), Inches(1.6), Inches(12.1), Inches(4.6)).table
for j, wdt in enumerate([4.6, 1.9, 1.7, 3.9]):
    tbl.columns[j].width = Inches(wdt)
for i, r in enumerate(rows):
    for j, v in enumerate(r):
        cell = tbl.cell(i, j)
        cell.text = v
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY if i == 0 else (CARD if i % 2 else WHITE)
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT if j in (1, 2) and i else PP_ALIGN.LEFT
        run = p.runs[0]
        run.font.size, run.font.name = Pt(14), BODY
        run.font.bold = i == 0 or (j == 2 and v not in ("0",))
        run.font.color.rgb = WHITE if i == 0 else (ORANGE if j == 2 and v != "0" else INK2)
        cell.margin_left = cell.margin_right = Inches(0.12)
text(s, 0.6, 6.4, 12, 0.4, "Ошибок уровня error нет. Плюс контроль свежести каждого источника.", size=13, color=MUTED)

# ======================= 10. Модель =======================
s = content_slide("Модель точнее нормы", "Козлов В.Н.",
                  "Почему прогноз по погоде: факт BTS приходит с опозданием на 2–3 месяца. Признаки — календарь и "
                  "погода дня, одинаково считаемые по METAR (история) и Open-Meteo (будущее). Лагов короче года нет — "
                  "утечки будущего нет, это проверяет тест. Проверка честная: каждый месяц прогнозируем моделью, "
                  "обученной только на прошлом. Интервал 10–90% — по ошибкам проверки.", "Прогноз")
text(s, 0.6, 1.6, 5.6, 4.5, [
    [("Что прогнозируем", {"bold": True, "color": NAVY})],
    "Долю вылетов с задержкой ≥ 15 мин и число вылетов — на каждый день до «сегодня + 7»",
    [("Признаки", {"bold": True, "color": NAVY})],
    "Календарь, праздники, погода дня: порывы, видимость, осадки, снег, гроза",
    [("Модель", {"bold": True, "color": NAVY})],
    "Градиентный бустинг против «нормы» (среднее по дню недели и месяцу / тот же день год назад)",
    [("Проверка", {"bold": True, "color": NAVY})],
    f"Скользящая: 6 месяцев, {md['n_days']} дней, каждый — моделью только на прошлом",
], size=15, color=INK2, spacing=6)
gain_d = (1 - md["model"]["mae"] / md["baseline"]["mae"]) * 100
gain_f = (1 - mf["model"]["mae"] / mf["baseline"]["mae"]) * 100
cd = CategoryChartData()
cd.categories = ["Доля задержек, п.п.", "Число вылетов, ×10 рейсов"]
cd.add_series("Норма", [md["baseline"]["mae"] * 100, mf["baseline"]["mae"] / 10])
cd.add_series("Модель", [md["model"]["mae"] * 100, mf["model"]["mae"] / 10])
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6.5), Inches(1.55), Inches(6.2), Inches(3.9), cd)
ch = gf.chart
style_chart(ch, legend=True, pct=False)
ch.plots[0].gap_width = 60
ch.plots[0].overlap = -10
for k, col in enumerate([RGBColor(0xB4, 0xB2, 0xAB), SKY]):
    sr = ch.plots[0].series[k]
    sr.format.fill.solid()
    sr.format.fill.fore_color.rgb = col
ch.plots[0].has_data_labels = True
dl = ch.plots[0].data_labels
dl.number_format, dl.number_format_is_linked, dl.position = '0.0', False, XL_LABEL_POSITION.OUTSIDE_END
dl.font.size, dl.font.color.rgb = Pt(12), INK2
ch.has_title = True
ch.chart_title.text_frame.text = "Средняя ошибка (MAE), меньше — лучше"
ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
ch.chart_title.text_frame.paragraphs[0].runs[0].font.color.rgb = INK2
for i, (v, l) in enumerate([(f"−{gain_d:.0f}%", "ошибка по доле задержек"), (f"−{gain_f:.0f}%", "ошибка по числу вылетов"),
                            (f"{md['model']['coverage']:.0f}%", "дней факт внутри интервала")]):
    x = 6.5 + i * 2.1
    box(s, x, 5.65, 1.95, 1.1, CARD)
    text(s, x + 0.15, 5.7, 1.7, 0.6, v, size=26, bold=True, color=ORANGE if i < 2 else NAVY, font=HEAD)
    text(s, x + 0.15, 6.27, 1.75, 0.45, l, size=11, color=INK2)

# ======================= 11. Прогноз на неделю =======================
s = content_slide("Прогноз на неделю: где нужен резерв", "Козлов В.Н.",
                  "Главный виджет дашборда отвечает на вопрос «Какую долю задержек ждать в ближайшие 7 дней и выше ли "
                  "она нормы?». Порог проблемного дня настраивается ползунком; под графиком система сама пишет вывод "
                  "— в какие дни нужен резерв и из-за каких погодных явлений. Дальше — живое демо дашборда.",
                  "Дашборд")
picture(s, "forecast_1", 0.6, 1.5, w=8.3, h=5.3)
qs = ["Какую долю задержек ждать и выше ли она нормы?", "Сколько вылетов ожидается?", "Насколько верить прогнозу?",
      "Какая погода ожидается и чем опасна?", "Какие условия сильнее бьют по пунктуальности?",
      "В какие часы задержки хуже всего?", "Можно ли доверять данным?"]
text(s, 9.3, 1.55, 3.4, 0.4, "Каждый виджет — ответ на вопрос", size=15, bold=True, color=NAVY)
for i, q in enumerate(qs):
    y = 2.1 + i * 0.66
    circle_num(s, 9.3, y + 0.03, 0.36, str(i + 1), fill=ORANGE if i == 0 else SKY, size=11)
    text(s, 9.8, y, 2.95, 0.6, q, size=12, color=INK2)

# ======================= 12. Дашборд целиком =======================
s = content_slide("Четыре страницы дашборда", "Козлов В.Н.",
                  "Живое демо: 1) «Прогноз» — подвигать порог; 2) «Погода и задержки» — влияние явлений; "
                  "3) «Данные» — исправить задержку у рейса, показать флаг «правлен вручную» и журнал правок; "
                  "4) «Журнал и качество» — демо сбоя 429 и повторный запуск с нулём новых строк.", "Дашборд")
shots = [("forecast_0", "Прогноз"), ("weather_2", "Погода и задержки"), ("data_0", "Данные"), ("ops_3", "Журнал и качество")]
for i, (nm, lab) in enumerate(shots):
    x, y = 0.6 + (i % 2) * 6.15, 1.5 + (i // 2) * 2.75
    box(s, x, y, 5.95, 2.6, CARD)
    picture(s, nm, x + 0.15, y + 0.15, w=5.65, h=2.0)
    text(s, x + 0.2, y + 2.2, 5.5, 0.3, lab, size=13, bold=True, color=NAVY)

# ======================= 13. Выводы =======================
s = prs.slides.add_slide(BLANK)
N[0] += 1
bg(s, NAVY)
text(s, 0.8, 0.6, 11, 0.8, "Выводы и ограничения", size=34, bold=True, font=HEAD, color=WHITE, name="Title")
concl = ["Полный цикл: 3 разнородных источника → хранение → очистка → контроль качества → прогноз → дашборд",
         "Загрузка инкрементальная, идемпотентная, устойчивая к сбоям, каждый запуск в журнале",
         "Гроза утраивает долю задержек; задержки копятся к вечеру",
         f"Модель точнее нормы на {gain_d:.0f}% (задержки) и {gain_f:.0f}% (число вылетов)"]
limits = ["Факт BTS приходит с лагом 2–3 месяца", "Один аэропорт: сеть и погода в других городах не видны",
          "Нет будущего расписания рейсов", "Модель учится на факте погоды, а работает на прогнозе"]
for col, (title, items, color) in enumerate([("Что сделано", concl, SKY), ("Ограничения", limits, ORANGE)]):
    x = 0.8 + col * 6.1
    text(s, x, 1.7, 5.6, 0.5, title, size=20, bold=True, color=color)
    for i, it in enumerate(items):
        y = 2.35 + i * 1.0
        circle_num(s, x, y + 0.05, 0.42, str(i + 1), fill=color, size=12)
        text(s, x + 0.6, y, 5.0, 0.9, it, size=15, color=WHITE)
text(s, 0.8, 6.6, 11.5, 0.5, "Спасибо! Код и инструкция: github.com/BuyBuy-Service/teterin", size=16, color=SKY_L)
s.notes_slide.notes_text_frame.text = ("Говорит: Селиванова А.К.\nКоротко итог и ограничения — честно. "
                                       "Дальше вопросы: кто отвечает на какие — в docs/demo-script.md.")

prs.core_properties.title = "AeroPulse — прогноз задержек рейсов ORD"
prs.core_properties.author = "Селиванова А.К., Козлов В.Н., Харлашкина А.В."
prs.save(OUT)
print("saved", OUT, "slides:", N[0])
