"""Сборка презентации для защиты на фирменном шаблоне МИСИС.   python report/build_deck.py

Берётся report/template/MISIS_presentation.pptx: слайды-примеры удаляются, новые слайды строятся на макетах
шаблона (логотип, плашки, колонтитул, номер слайда — из макетов). Графики — нативные диаграммы PowerPoint
в цветах брендбука, экраны дашборда — скриншоты (report/screenshots.py).
В заметках к каждому слайду — кто рассказывает и что говорить."""
import copy
import sqlite3

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from common import HERE, ROOT, config, facts, fmt, trimmed

TEMPLATE = HERE / "template" / "MISIS_presentation.pptx"
OUT = ROOT / "report" / "Презентация_AeroPulse.pptx"
DECK_NAME = "AeroPulse: прогноз задержек рейсов аэропорта ORD"
F = facts()
md, mf = F["metrics"]["dep_del15_share"], F["metrics"]["dep_flown"]
GAIN_D = (1 - md["model"]["mae"] / md["baseline"]["mae"]) * 100
GAIN_F = (1 - mf["model"]["mae"] / mf["baseline"]["mae"]) * 100

# цвета брендбука (тема шаблона Misis)
BLUE, CYAN, NAVY, GRAY = RGBColor(0x05, 0x41, 0xF0), RGBColor(0x37, 0xEB, 0xFF), RGBColor(0x0A, 0x1E, 0x64), RGBColor(0x50, 0x55, 0x69)
BLUE_L = RGBColor(0xB4, 0xC6, 0xFB)  # светлый оттенок фирменного синего — фон для «обычных» столбцов
LINE, WHITE = RGBColor(0xD5, 0xD9, 0xE6), RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Tahoma"

prs = Presentation(TEMPLATE)
# убираем слайды-примеры шаблона (их картинки и диаграммы не попадут в файл — на них больше нет ссылок)
sld_ids = prs.slides._sldIdLst
for sld in list(sld_ids):
    prs.part.drop_rel(sld.rId)
    sld_ids.remove(sld)
L = {l.name: l for l in prs.slide_layouts}


# ---------------- помощники ----------------
def ph(slide, idx):
    for p in slide.placeholders:
        if p.placeholder_format.idx == idx:
            return p
    raise KeyError(idx)


def place(p, x, y, w, h):
    """Рамку плейсхолдера задаём целиком: если поменять одно измерение, остальные станут нулевыми."""
    p.left, p.top, p.width, p.height = Inches(x), Inches(y), Inches(w), Inches(h)


def no_bullet(par):
    pPr = par._p.get_or_add_pPr()
    pPr.set("indent", "0")
    pPr.set("marL", "0")
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    etree.SubElement(pPr, qn("a:buNone"))


def drop_unused(slide, keep):
    """Удаляет незаполненные плейсхолдеры, чтобы в режиме редактирования не торчали подсказки шаблона."""
    for p in list(slide.placeholders):
        if p.placeholder_format.idx not in keep:
            p._element.getparent().remove(p._element)


def add_layout_ph(slide, idx):
    """Колонтитул и номер слайда python-pptx не копирует из макета — переносим их сами."""
    for sp in slide.slide_layout.placeholders:
        if sp.placeholder_format.idx == idx:
            el = copy.deepcopy(sp._element)
            slide.shapes._spTree.append(el)
            return slide.shapes[-1]


def fill(p, paras, size=None, color=None, bold_first=False):
    """paras: строка или список абзацев; абзац — строка или список (текст, {bold, color, size})."""
    tf = p.text_frame
    tf.clear()
    paras = paras if isinstance(paras, list) else [paras]
    for i, para in enumerate(paras):
        par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        for t, o in (para if isinstance(para, list) else [(para, {})]):
            r = par.add_run()
            r.text = t
            if o.get("bold") or (bold_first and i == 0):
                r.font.bold = True
            if o.get("color") or color:
                r.font.color.rgb = o.get("color", color)
            if o.get("size") or size:
                r.font.size = Pt(o.get("size", size))
    return p


def new_slide(layout, title=None, speaker=None, notes="", keep=()):
    s = prs.slides.add_slide(L[layout])
    if title is not None:
        fill(ph(s, 0), title)
    if speaker:  # колонтитул: название, докладчик, номер слайда
        if any(p.placeholder_format.idx == 21 for p in s.slide_layout.placeholders):
            fill(ph(s, 21), speaker)
        f = add_layout_ph(s, 19)
        if f is not None:
            fill(f, DECK_NAME)
        add_layout_ph(s, 20)
    drop_unused(s, set(keep) | {0, 19, 20, 21})
    s.notes_slide.notes_text_frame.text = (f"Говорит: {speaker}.\n" if speaker else "") + notes
    return s


def text(slide, x, y, w, h, paras, size=24, color=GRAY, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         font=FONT, spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = paras if isinstance(paras, list) else [paras]
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
            r.font.color.rgb = o.get("color", color)
    return tb


def rect(slide, x, y, w, h, fill_color, rounded=False, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        shp.adjustments[0] = 0.12
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_color
    if line:
        shp.line.color.rgb = line
        shp.line.width = Pt(1.5)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def label_in(shp, t, size=24, color=WHITE, bold=True, font=FONT):
    tf = shp.text_frame
    tf.margin_left = tf.margin_right = Inches(0.1)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = t
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, font


def picture(slide, name, x, y, w, h, frame=True):
    path = trimmed(name)
    iw, ih = Image.open(path).size
    k = min(w / iw, h / ih)
    pw, phh = iw * k, ih * k
    pic = slide.shapes.add_picture(str(path), Inches(x + (w - pw) / 2), Inches(y + (h - phh) / 2),
                                   Inches(pw), Inches(phh))
    if frame:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(1)
    return pic


def chart_style(ch, pct=True, legend=False, size=18):
    ch.font.size, ch.font.name, ch.font.color.rgb = Pt(size), FONT, GRAY
    ch.has_legend = legend
    if legend:
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.TOP, False
        ch.legend.font.size = Pt(size)
    va = ch.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = LINE
    va.format.line.fill.background()
    va.tick_labels.font.color.rgb = GRAY
    if pct:
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "0%", False
    ca = ch.category_axis
    ca.format.line.color.rgb = LINE
    ca.has_major_gridlines = False


def chart_title(ch, t, size=18):
    ch.has_title = True
    ch.chart_title.text_frame.text = t
    r = ch.chart_title.text_frame.paragraphs[0].runs[0]
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), False, GRAY, FONT


def color_series(ser, base, highlight=None, idxs=()):
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = base
    for i in idxs:
        pt = ser.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = highlight


def cell_border(cell, side, color="D5D9E6", w=12700):
    """Тонкая линия у ячейки (side: L/R/T/B) — как в таблице шаблона."""
    tcPr = cell._tc.get_or_add_tcPr()
    tag = qn(f"a:ln{side}")
    for old in tcPr.findall(tag):
        tcPr.remove(old)
    ln = etree.SubElement(tcPr, tag, w=str(w), cap="flat", cmpd="sng", algn="ctr")
    sf = etree.SubElement(ln, qn("a:solidFill"))
    etree.SubElement(sf, qn("a:srgbClr"), val=color)
    etree.SubElement(ln, qn("a:prstDash"), val="solid")


def no_border(cell, side):
    tcPr = cell._tc.get_or_add_tcPr()
    tag = qn(f"a:ln{side}")
    for old in tcPr.findall(tag):
        tcPr.remove(old)
    ln = etree.SubElement(tcPr, tag, w="0")
    etree.SubElement(ln, qn("a:noFill"))


def section(title, who, layout="Раздел или глава", notes=""):
    s = prs.slides.add_slide(L[layout])
    fill(ph(s, 0), title, size=110)
    t = ph(s, 0)
    text(s, t.left / 914400, (t.top + t.height) / 914400 + 0.2, t.width / 914400, 0.8, who, size=32, color=CYAN)
    s.notes_slide.notes_text_frame.text = f"Говорит: {who}.\n{notes}"
    return s


SEL, KHA, KOZ = "Селиванова А.К.", "Харлашкина А.В.", "Козлов В.Н."

# ======================= 1. Титул =======================
s = prs.slides.add_slide(L["Титульный слайд"])
fill(ph(s, 0), "AeroPulse: прогноз задержек рейсов аэропорта", size=72)
fill(ph(s, 1), ["Селиванова А.К., Козлов В.Н., Харлашкина А.В.", "студенты группы МПИ-25-4"], size=32)
d10 = add_layout_ph(s, 10)
place(d10, 1.42, 12.98, 10.88, 0.8)
fill(d10, "Проектная работа по дисциплине «Визуализация данных» · преподаватель Тетерин Н.А. · 2026", size=20)
s.notes_slide.notes_text_frame.text = (
    f"Говорит: {SEL}.\nПредставиться командой. Тема №7 «Гражданская авиация»: прогнозируем число рейсов и долю "
    "задержек в аэропорту Chicago O’Hare. Порядок: Селиванова — задача и погода, Харлашкина — данные и надёжность, "
    "Козлов — прогноз и живое демо.")

# ======================= Раздел 1 =======================
section("Задача и погода", SEL)

# ======================= Кому и зачем =======================
s = new_slide("Акцентные плашки", "Кому и зачем нужна система", SEL,
              "Пользователь — операционный менеджер аэропорта или авиакомпании. Его решение — нужен ли резерв "
              "персонала, экипажей и стоек на ближайшие дни. Погода прогнозируема на неделю вперёд, значит и задержки "
              "можно предвидеть. Почему США: в России статистика задержек не публикуется.", keep=(12, 23, 25))
fill(ph(s, 12), [[("Пользователь — ", {"bold": True, "color": NAVY}), ("операционный менеджер аэропорта "
                  "или авиакомпании", {})],
                 [("Решение — ", {"bold": True, "color": NAVY}), ("нужен ли на ближайшие дни резерв персонала, "
                  "экипажей и стоек регистрации", {})],
                 [("Почему Чикаго, а не российский аэропорт — ", {"bold": True, "color": NAVY}),
                  ("в России статистика пунктуальности не публикуется, Минтранс США раскрывает данные "
                   "о каждом рейсе", {})]], size=30)
for par in ph(s, 12).text_frame.paragraphs:
    par.space_after = Pt(18)
fill(ph(s, 23), f"{F['del15'] * 100:.0f}%")
fill(ph(s, 25), f"вылетов задерживаются на 15 минут и больше — при {fmt(F['avg_flown'])} вылетах в сутки")

# ======================= Источники =======================
s = new_slide("Три колонки", "Три разнородных источника данных", SEL,
              "Разнородность — по способу получения и формату: пакетные ZIP-архивы, текстовые сводки, JSON API. "
              "Слабоструктурированный источник — METAR: текст фиксированного формата с показаниями датчиков. "
              "Все источники проверили реальными запросами до начала разработки.", keep=(12, 13, 22, 23, 24, 25))
cols = [(13, 12, "BTS — рейсы", fmt(F["flights"]), "рейсов ORD за 24 месяца",
         ["ZIP-архивы с CSV, раз в месяц", "план и факт, задержка, отмена, причины", "структурированные данные"]),
        (22, 24, "METAR — погода", fmt(F["metar"]), "текстовых сводок метеостанции",
         ["ежечасные сводки аэропорта", "ветер, видимость, облака, явления", "слабоструктурированные: текст"]),
        (23, 25, "Open-Meteo — прогноз", "168", "часов прогноза погоды",
         ["JSON API", "осадки, снег, порывы, видимость", "структурированные данные"])]
for i, (h_idx, b_idx, head, big, sub, items) in enumerate(cols):
    x = ph(s, h_idx).left / 914400
    fill(ph(s, h_idx), head)
    fill(ph(s, b_idx), [[(f"{big} ", {"bold": True, "color": NAVY}), (sub, {})]] + ["— " + it for it in items],
         size=26)

# ======================= METAR -> признаки =======================
s = new_slide("Буллиты", "METAR → признаки", SEL,
              "Числовые группы разбирает библиотека metar, погодные явления — наш собственный разбор токенов. "
              "Категория полётных условий — по правилам FAA. Из 23,6 тыс. сводок не разобрана одна — битая "
              "автоматическая. Затем каждый вылет сопоставляем с последней сводкой не старше 90 минут до вылета.",
              keep=())
parts = [("KORD", "аэропорт"), ("161451Z", "16-е число\n14:51 UTC"), ("27015G25KT", "ветер 15 уз\nпорывы 25"),
         ("3SM", "видимость\n3 мили"), ("-SN BR", "слабый снег\nдымка"), ("OVC008", "облака\n800 футов"),
         ("M02/M04", "−2 °C\nточка росы −4")]
x = 1.42
for tok, mean in parts:
    w = 0.75 + 0.33 * len(tok)
    key = tok in ("27015G25KT", "3SM", "-SN BR", "OVC008")
    label_in(rect(s, x, 4.1, w, 1.4, BLUE if key else NAVY, rounded=True), tok, size=30, font="Courier New")
    text(s, x, 5.7, w, 1.2, mean.split("\n"), size=20, color=GRAY, align=PP_ALIGN.CENTER)
    x += w + 0.22
text(s, 1.42, 7.55, 23.7, 0.7, "Категория полётных условий (FAA) — по видимости и высоте облаков", size=28, bold=True,
     color=NAVY)
cats = [("VFR", "видимость > 5 миль,\nоблака > 3000 футов", CYAN, NAVY), ("MVFR", "3–5 миль\nили 1000–3000 футов", RGBColor(0x6E, 0x9B, 0xF7), WHITE),
        ("IFR", "1–3 мили\nили 500–1000 футов", BLUE, WHITE), ("LIFR", "< 1 мили\nили < 500 футов", NAVY, WHITE)]
for i, (c, d, bgc, fg) in enumerate(cats):
    xx = 1.42 + i * 5.97
    rect(s, xx, 8.45, 5.7, 2.55, bgc, rounded=True)
    text(s, xx + 0.35, 8.7, 5.0, 0.8, c, size=40, bold=True, color=fg)
    text(s, xx + 0.35, 9.6, 5.0, 1.3, d.split("\n"), size=20, color=fg)
text(s, 1.42, 11.5, 23.7, 1.3, [[(f"{fmt(F['metar_ok'])} из {fmt(F['metar'])} ", {"bold": True, "color": BLUE}),
                                 ("сводок разобраны. Каждый вылет сопоставлен с последней сводкой не старше 90 минут "
                                  "до планового вылета — так погода связывается с конкретным рейсом.", {})]], size=24)

# ======================= Гроза =======================
s = new_slide("Диаграмма", "Гроза — 67% задержек", SEL,
              "Главный результат по погоде. Для каждого вылета взяли погоду в момент вылета. Без опасных явлений "
              "задержано 23%, при грозе — 67%. Вывод для менеджера: гроза и ледяной дождь в прогнозе — сигнал готовить "
              "резерв в первую очередь.", keep=(11, 22))
phen = [("Без явлений", .23), ("Порывы ≥ 30 уз", .34), ("Дождь", .34), ("Туман", .45), ("Снег", .46),
        ("Ледяной дождь", .54), ("Гроза", .67)]
cd = CategoryChartData()
cd.categories = [p[0] for p in phen]
cd.add_series("Доля задержанных вылетов", [p[1] for p in phen])
ch = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(1.2), Inches(3.9), Inches(14.6), Inches(9.3), cd).chart
chart_style(ch)
ch.plots[0].gap_width = 45
color_series(ch.plots[0].series[0], BLUE_L, BLUE, (5, 6))
ch.plots[0].has_data_labels = True
dl = ch.plots[0].data_labels
dl.number_format, dl.number_format_is_linked, dl.position = "0%", False, XL_LABEL_POSITION.OUTSIDE_END
dl.font.size, dl.font.bold, dl.font.color.rgb = Pt(20), True, NAVY
ch.value_axis.maximum_scale = 0.8
chart_title(ch, "Доля вылетов, задержанных ≥ 15 мин, при погоде в момент вылета")
fill(ph(s, 11), "Гроза утраивает долю задержек")
fill(ph(s, 22), ["Без опасных явлений — 23%.", "От хорошей погоды (VFR) к полётам по приборам (IFR) — с 24% до 34%.",
                 "Ледяной дождь и снег — следующие по силе."], size=26)
place(ph(s, 22), 17.56, 4.4, 7.59, 8.0)

# ======================= Задержки к вечеру =======================
s = new_slide("График 1", "Задержки копятся к вечеру", SEL,
              "По часам: утром задержано около 10% вылетов, к 19–22 часам — до 38%: опоздания передаются по цепочке "
              "рейсов. Поэтому резерв нужнее вечерним сменам. По причинам: официальная «погода» — лишь 9% минут, но "
              "обычная непогода записывается в NAS и затем всплывает как «поздний прилёт самолёта».", keep=(11, 22))
con = sqlite3.connect(config.DB_PATH)
hrs = con.execute("""SELECT crs_dep_time/100 h, avg(dep_del15) FROM flights WHERE direction='departure'
                     AND cancelled=0 AND dep_del15 IS NOT NULL AND is_deleted=0 GROUP BY 1 HAVING count(*) > 5000
                     ORDER BY 1""").fetchall()
con.close()
cd = CategoryChartData()
cd.categories = [f"{int(h):02d}" for h, _ in hrs]
cd.add_series("Доля задержанных вылетов", [v for _, v in hrs])
ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1.2), Inches(4.7), Inches(15.3), Inches(8.6), cd).chart
chart_style(ch)
ch.plots[0].gap_width = 40
color_series(ch.plots[0].series[0], BLUE_L, BLUE, [i for i, (_, v) in enumerate(hrs) if v >= 0.35])
chart_title(ch, "Доля задержанных вылетов по часу вылета (местное время)")
fill(ph(s, 11), "Минуты задержки по причинам")
c = F["causes"]
causes = [("Поздний прилёт самолёта", c["late"]), ("Перевозчик", c["carrier"]), ("Авиасистема (NAS)", c["nas"]),
          ("Погода", c["weather"])]
for i, (name, share) in enumerate(causes):
    y = 4.1 + i * 1.35
    text(s, 17.56, y, 5.6, 0.5, name, size=22, color=GRAY)
    text(s, 23.2, y, 1.95, 0.5, f"{share * 100:.0f}%", size=22, bold=True, color=NAVY, align=PP_ALIGN.RIGHT)
    rect(s, 17.56, y + 0.6, 7.59, 0.32, RGBColor(0xEE, 0xF1, 0xF8))
    rect(s, 17.56, y + 0.6, max(0.1, 7.59 * share / causes[0][1]), 0.32, BLUE if name == "Погода" else BLUE_L)
p22 = ph(s, 22)
place(p22, 17.56, 9.8, 7.59, 3.2)
fill(p22, "Обычная непогода записывается в NAS и «поздний прилёт», поэтому «погода» в отчётности занижена.", size=22)

# ======================= Раздел 2 =======================
section("Данные и надёжность", KHA, "Раздел или глава 1")

# ======================= Архитектура =======================
s = new_slide("Изображения 1", "Как устроена обработка", KHA,
              "Слои: сырые данные хранятся как пришли (ZIP с хэшем, тексты METAR, JSON), затем очищенные таблицы, "
              "витрина по дням и прогноз. Каждый шаг — отдельная задача с единой обвязкой: журнал, отметка загрузки, "
              "повторы. Ошибка одного шага не валит остальные. Запуск одной командой или по расписанию.",
              keep=(12, 23, 25))
fill(ph(s, 12), [[("1  Сырые данные — ", {"bold": True, "color": NAVY}), ("как пришли: ZIP с хэшем, тексты METAR, JSON", {})],
                 [("2  Очищенные — ", {"bold": True, "color": NAVY}), ("рейсы, разобранная погода, прогноз", {})],
                 [("3  Витрина — ", {"bold": True, "color": NAVY}), ("день × рейсы × погода", {})],
                 [("4  Прогноз — ", {"bold": True, "color": NAVY}), ("модель, проверка, версии", {})]], size=24)
fill(ph(s, 23), "Стек")
fill(ph(s, 25), "Python · SQLite · pandas · scikit-learn · Streamlit · Планировщик Windows", size=22)
picture(s, "ops_1", 13.63, 2.6, 11.51, 10.2)

# ======================= Надёжность =======================
s = new_slide("Акцентные плашки 1", "Повторный запуск — 0 новых строк", KHA,
              "Четыре требования методички к загрузке. Инкрементальность — отметка «докуда загружено» по каждому "
              "источнику. Идемпотентность — запись по естественным ключам, хэши файлов, данные и отметка в одной "
              "транзакции. Устойчивость — повторы с паузой и учётом Retry-After, карантин битых файлов. Журнал — "
              "каждая строка = запуск. Проверено: первый запуск — 1,34 млн рейсов, повторный — 0. Тут Козлов "
              "показывает демо сбоя 429 на странице «Журнал и качество».", keep=(12, 26, 27, 28, 29, 30))
fill(ph(s, 26), "Только новое, без дублей")
fill(ph(s, 12), "Догружаются только новые месяцы и сводки; повтор ничего не задваивает: ключи, хэши, одна транзакция",
     size=24)
fill(ph(s, 28), "Устойчиво, с журналом")
fill(ph(s, 27), "Таймауты, до 4 повторов с паузой, карантин битых файлов; каждый запуск — строка в журнале", size=24)
fill(ph(s, 30), "Проверка на живых данных")
fill(ph(s, 29), [[(fmt(F["flights"]), {"bold": True, "size": 60})], "рейсов — первый запуск, ~33 минуты",
                 [("0", {"bold": True, "size": 60, "color": CYAN})], "новых строк при повторном запуске"], size=24)

# ======================= Качество =======================
s = new_slide("Таблица", "Контроль качества", KHA,
              "14 правил, запускаются после каждой загрузки, результаты на дашборде с примерами записей. Ошибок "
              "уровня error нет. Предупреждения — реальные особенности: сверхдолгие задержки (данные верные), "
              "отменённые рейсы с временем вылета — самолёт вылетел и вернулся, праздничные провалы объёма, "
              "битая сводка METAR.", keep=(11, 22))
fill(ph(s, 11), "14 правил")
fill(ph(s, 22), "после каждой загрузки; нашли реальные проблемы, ошибок уровня error нет")
rows = [("Правило", "Проверено", "Нарушений", "Что это"),
        ("Задержка вне −60…2000 мин", "1 310 479", "26", "реальные задержки > 33 ч"),
        ("Отменённый рейс со временем вылета", "28 117", "1 568", "вылетел и вернулся"),
        ("Объём вылетов вне ±3σ", "730 дней", "7", "праздники: День благодарения, 4 июля"),
        ("Перерыв в METAR > 2 ч", "23 588", "3", "пропуски наблюдений"),
        ("Сводка METAR не разобрана", "23 588", "1", "битая автоматическая сводка"),
        ("DepDel15 ≠ минутам задержки", "1 310 479", "0", "согласовано"),
        ("Погода вне физических диапазонов", "23 587", "0", "—")]
tbl = s.shapes.add_table(len(rows), 4, Inches(1.52), Inches(5.6), Inches(23.62), Inches(7.4)).table
tbl.first_row = False
tbl.horz_banding = False
for j, wdt in enumerate([8.6, 3.6, 3.4, 8.02]):
    tbl.columns[j].width = Inches(wdt)
for i, r in enumerate(rows):
    for j, v in enumerate(r):
        cell = tbl.cell(i, j)
        cell.text = v
        cell.fill.background()
        cell.margin_left = cell.margin_right = Inches(0.12)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT if j in (1, 2) else PP_ALIGN.LEFT
        run = p.runs[0]
        run.font.size, run.font.name = Pt(22 if i else 20), FONT
        run.font.bold = (j == 2 and i and v != "0")
        run.font.color.rgb = BLUE if i == 0 or (j == 2 and v != "0") else GRAY
        for side in ("L", "R", "T"):
            no_border(cell, side)
        cell_border(cell, "B", "0541F0" if i == 0 else "D5D9E6", 19050 if i == 0 else 9525)

# ======================= Раздел 3 =======================
section("Прогноз и дашборд", KOZ)

# ======================= Модель =======================
s = new_slide("Акцентные плашки 2", "Модель точнее нормы", KOZ,
              "Почему прогноз по погоде: факт BTS приходит с опозданием на 2–3 месяца. Признаки — календарь и погода "
              "дня, одинаково считаемые по METAR (история) и Open-Meteo (будущее). Лагов короче года нет — утечки "
              "будущего нет, это проверяет тест. Проверка честная: каждый месяц прогнозируем моделью, обученной только "
              "на прошлом. Интервал 10–90% — по ошибкам проверки.", keep=(14, 15, 27, 28))
fill(ph(s, 28), "Как строится прогноз")
fill(ph(s, 27), ["Цели: доля вылетов с задержкой ≥ 15 мин и число вылетов на каждый день до «сегодня + 7»",
                 "Признаки: календарь, праздники, погода дня",
                 "Модель — градиентный бустинг; сравнение с «нормой» по дню недели и месяцу",
                 f"Проверка: 6 месяцев, {md['n_days']} дней, каждый — моделью только на прошлом"], size=22)
for par in ph(s, 27).text_frame.paragraphs:
    par.space_after = Pt(10)
place(ph(s, 15), 13.45, 4.4, 4.3, 1.7)
fill(ph(s, 15), f"−{GAIN_D:.0f}%", size=80, color=BLUE)
place(ph(s, 14), 13.51, 6.2, 4.2, 1.6)
fill(ph(s, 14), "ошибка по доле задержек относительно нормы")
cd = CategoryChartData()
cd.categories = ["Доля задержек, п.п.", "Число вылетов, ×10"]
cd.add_series("Норма", [md["baseline"]["mae"] * 100, mf["baseline"]["mae"] / 10])
cd.add_series("Модель", [md["model"]["mae"] * 100, mf["model"]["mae"] / 10])
ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(17.9), Inches(3.9), Inches(7.6), Inches(9.0), cd).chart
chart_style(ch, pct=False, legend=True)
ch.plots[0].gap_width, ch.plots[0].overlap = 60, -10
color_series(ch.plots[0].series[0], BLUE_L)
color_series(ch.plots[0].series[1], BLUE)
ch.plots[0].has_data_labels = True
dl = ch.plots[0].data_labels
dl.number_format, dl.number_format_is_linked, dl.position = "0.0", False, XL_LABEL_POSITION.OUTSIDE_END
dl.font.size, dl.font.color.rgb = Pt(18), NAVY
chart_title(ch, "Средняя ошибка (MAE), меньше — лучше")
text(s, 13.45, 8.6, 4.3, 1.7, f"−{GAIN_F:.0f}%", size=80, color=BLUE)
text(s, 13.51, 10.4, 4.2, 1.6, "ошибка по числу вылетов относительно нормы", size=20, color=GRAY)

# ======================= Прогноз на неделю =======================
s = new_slide("Диаграмма", "Прогноз на неделю", KOZ,
              "Главный виджет отвечает на вопрос «Какую долю задержек ждать в ближайшие 7 дней и выше ли она нормы?». "
              "Порог проблемного дня настраивается ползунком; под графиком система сама пишет вывод — в какие дни "
              "нужен резерв и из-за каких явлений. Дальше — живое демо дашборда.", keep=(11, 22))
picture(s, "forecast_1", 1.2, 4.0, 15.4, 9.2)
fill(ph(s, 11), "Каждый виджет — ответ на вопрос")
qs = ["Какую долю задержек ждать и выше ли она нормы?", "Сколько вылетов ожидается?", "Насколько верить прогнозу?",
      "Какая погода ожидается и чем опасна?", "Какие условия сильнее бьют по пунктуальности?",
      "В какие часы задержки хуже всего?", "Можно ли доверять данным?"]
p22 = ph(s, 22)
place(p22, 17.56, 4.4, 7.59, 8.8)
fill(p22, [[(f"{i}  ", {"bold": True, "color": BLUE}), (q, {})] for i, q in enumerate(qs, 1)], size=22)
for par in p22.text_frame.paragraphs:
    par.space_after = Pt(12)

# ======================= Дашборд =======================
s = new_slide("Изображения", "Четыре страницы дашборда", KOZ,
              "Живое демо: 1) «Прогноз» — подвигать порог; 2) «Погода и задержки» — влияние явлений; 3) «Данные» — "
              "исправить задержку у рейса, показать флаг «правлен вручную» и журнал правок; 4) «Журнал и качество» — "
              "демо сбоя 429 и повторный запуск с нулём новых строк.", keep=())
shots = [("forecast_0", "Прогноз"), ("weather_2", "Погода и задержки"), ("data_0", "Данные"), ("ops_3", "Журнал и качество")]
for i, (nm, lab) in enumerate(shots):
    x, y = 1.42 + (i % 2) * 12.0, 4.7 + (i // 2) * 4.55
    picture(s, nm, x, y, 11.6, 3.6)
    text(s, x, y + 3.7, 11.6, 0.6, lab, size=22, bold=True, color=NAVY)

# ======================= Выводы =======================
s = new_slide("Буллиты", "Выводы и ограничения", SEL,
              "Итог: цель достигнута — система закрывает полный цикл работы с данными. Главные находки и честные "
              "ограничения. Дальше вопросы — кто отвечает на какие, в docs/demo-script.md.", keep=(11, 12, 22, 23))
fill(ph(s, 11), "Цель достигнута: полный цикл от сбора данных до прогноза и дашборда", size=34)
blocks = [(12, "Что сделано", ["3 разнородных источника, один слабоструктурированный",
                               "Загрузка инкрементальная, идемпотентная, устойчивая; журнал запусков",
                               "14 проверок качества, 4 страницы дашборда"]),
          (22, "Что выяснили", ["Гроза утраивает долю задержек", "Задержки копятся к вечеру — до 38%",
                                f"Модель точнее нормы на {GAIN_D:.0f}% и {GAIN_F:.0f}%"]),
          (23, "Ограничения", ["Факт BTS — с лагом 2–3 месяца", "Один аэропорт: сеть и погода в других городах не видны",
                               "Модель учится на факте погоды, работает на прогнозе"])]
for idx, head, items in blocks:
    fill(ph(s, idx), [[(head, {"bold": True, "color": BLUE, "size": 30})]] + items, size=24)
    for par in ph(s, idx).text_frame.paragraphs:
        par.space_after = Pt(14)
    no_bullet(ph(s, idx).text_frame.paragraphs[0])

# ======================= Заключительный =======================
s = prs.slides.add_slide(L["Заключительный"])
fill(ph(s, 0), ["Спасибо", "за внимание!"])
fill(ph(s, 22), ["Селиванова А.К., Козлов В.Н., Харлашкина А.В.", "МПИ-25-4, НИТУ МИСИС, 2026"])
s.notes_slide.notes_text_frame.text = "Вопросы. Кто отвечает на какие — в docs/demo-script.md."

prs.core_properties.title = DECK_NAME
prs.core_properties.author = "Селиванова А.К., Козлов В.Н., Харлашкина А.В."
prs.save(OUT)
print("saved", OUT, "slides:", len(prs.slides))
