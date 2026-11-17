"""Схемы для отчёта: архитектура, модель данных, алгоритм загрузки, алгоритм прогноза.
    python report/diagrams.py   -> report/img/diagram_*.png"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon  # noqa: E402

OUT = Path(__file__).parent / "img"
OUT.mkdir(exist_ok=True)
plt.rcParams.update({"font.family": "Arial", "font.size": 10})
BLUE, NAVY, CYAN, GRAY = "#0541F0", "#0A1E64", "#37EBFF", "#505569"
FILL = {"src": "#E6ECFE", "proc": "#FFFFFF", "store": "#EEF1F8", "out": "#E3FBFF", "bad": "#FDECEC", "dec": "#FFF6E0"}
EDGE = {"src": BLUE, "proc": NAVY, "store": GRAY, "out": "#0B8FA3", "bad": "#C0392B", "dec": "#B7791F"}


class Diagram:
    def __init__(self, w, h):
        self.fig, self.ax = plt.subplots(figsize=(w, h))
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(0, h)
        self.ax.axis("off")
        self.p = {}

    def box(self, key, x, y, w, h, text, kind="proc", size=10, bold=False, align="center", diamond=None):
        """x, y — центр блока."""
        if kind == "dec" if diamond is None else diamond:
            pts = [(x - w / 2, y), (x, y + h / 2), (x + w / 2, y), (x, y - h / 2)]
            patch = Polygon(pts, closed=True, fc=FILL[kind], ec=EDGE[kind], lw=1.4)
        else:
            patch = FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                   fc=FILL[kind], ec=EDGE[kind], lw=1.4)
        self.ax.add_patch(patch)
        tx = x if align == "center" else x - w / 2 + 0.12
        self.ax.text(tx, y, text, ha=align, va="center", fontsize=size, color="#111",
                     fontweight="bold" if bold else "normal", linespacing=1.25)
        self.p[key] = patch

    def group(self, x0, y0, x1, y1, title):
        self.ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0.02,rounding_size=0.2",
                                         fc="none", ec="#B4BCD0", lw=1, ls="--"))
        self.ax.text(x0 + 0.12, y1 - 0.08, title, ha="left", va="top", fontsize=9, color=GRAY, style="italic")

    def arrow(self, a, b, label=None, style="-|>", ls="-", color="#333", rad=0.0, lpos=0.5, ldx=0.0, ldy=0.12):
        ar = self.ax.annotate("", xy=(0, 0), xytext=(0, 0), arrowprops=dict(
            arrowstyle=style, color=color, lw=1.2, ls=ls, patchA=self.p[a], patchB=self.p[b],
            shrinkA=2, shrinkB=2, connectionstyle=f"arc3,rad={rad}"))
        ca, cb = self._center(a), self._center(b)
        ar.xy, ar.xyann = cb, ca
        if label:
            mx, my = ca[0] + (cb[0] - ca[0]) * lpos + ldx, ca[1] + (cb[1] - ca[1]) * lpos + ldy
            self.ax.text(mx, my, label, ha="center", va="bottom", fontsize=8.5, color=GRAY,
                         bbox=dict(fc="white", ec="none", pad=0.5))

    def _center(self, k):
        bb = self.p[k].get_extents().transformed(self.ax.transData.inverted())
        return ((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)

    def save(self, name):
        self.fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(self.fig)


def architecture():
    d = Diagram(13, 7.3)
    d.group(0.2, 1.2, 2.9, 6.3, "Источники")
    d.box("bts", 1.55, 5.3, 2.4, 0.9, "BTS On-Time\nZIP с CSV, раз в месяц", "src")
    d.box("metar", 1.55, 3.85, 2.4, 1.1, "IEM METAR\nтекст сводок: ORD\n+ 10 аэропортов сети", "src")
    d.box("om", 1.55, 2.3, 2.4, 0.9, "Open-Meteo\nJSON-прогноз на 7 дней", "src")
    d.box("sched", 4.65, 6.85, 4.8, 0.6, "Запуск: Планировщик Windows / кнопка в дашборде", "dec", size=9,
          diamond=False)
    d.group(3.3, 0.3, 6.0, 6.3, "Обработка (pipeline.py)")
    d.box("ing", 4.65, 5.0, 2.4, 1.5, "Загрузка\nжурнал запусков,\nотметки загрузки,\nповторы при сбоях", "proc")
    d.box("tr", 4.65, 3.3, 2.4, 0.9, "Разбор METAR\nи очистка", "proc")
    d.box("mart", 4.65, 2.1, 2.4, 0.8, "Сборка витрины", "proc")
    d.box("dq", 4.65, 0.9, 2.4, 0.9, "Проверки качества\nочищенных данных", "proc")
    d.group(6.4, 0.3, 9.4, 6.3, "Хранилище SQLite")
    d.box("raw", 7.9, 5.2, 2.6, 1.0, "raw: ZIP + SHA-256,\nтексты METAR, JSON", "store")
    d.box("core", 7.9, 3.8, 2.6, 1.0, "очищенные: рейсы,\nпогода, прогноз погоды", "store")
    d.box("daily", 7.9, 2.45, 2.6, 0.8, "витрина: день × рейсы\n× погода", "store")
    d.box("ops", 7.9, 1.0, 2.6, 0.9, "служебные: журнал,\nкачество, правки", "store")
    d.box("model", 11.2, 5.0, 2.6, 1.1, "Модель\nобучение, проверка,\nпрогноз на 7 дней", "proc")
    d.box("ui", 11.2, 2.9, 2.6, 1.5, "Дашборд Streamlit\nПрогноз · Погода\nДанные · Журнал", "out")
    d.box("user", 11.2, 0.9, 2.6, 0.9, "Менеджер: решения,\nправки данных, импорт", "src")
    for s_ in ("bts", "metar", "om"):
        d.arrow(s_, "ing")
    d.arrow("sched", "ing", ls=":")
    d.arrow("ing", "raw")
    d.arrow("raw", "tr", ls="--")
    d.arrow("tr", "core")
    d.arrow("core", "mart", ls="--")
    d.arrow("mart", "daily")
    d.arrow("dq", "ops")
    d.arrow("daily", "model")
    d.arrow("model", "ui")
    d.arrow("daily", "ui")
    d.arrow("ops", "ui")
    d.arrow("ui", "user", style="<|-|>")
    d.save("diagram_architecture.png")


def data_model():
    d = Diagram(13, 6.2)
    t = lambda k, x, y, w, h, title, fields, kind: d.box(  # noqa: E731
        k, x, y, w, h, f"{title}\n" + "\n".join(fields), kind, size=8.5)
    t("raw_files", 1.6, 5.1, 2.8, 1.3, "raw_files", ["PK: source, sha256", "period, url, path"], "store")
    t("raw_metar", 1.6, 3.3, 2.8, 1.2, "raw_metar", ["PK: station, время, текст"], "store")
    t("raw_forecast", 1.6, 1.5, 2.8, 1.1, "raw_forecast", ["UNIQUE: sha256", "payload_json"], "store")
    t("flights", 5.4, 5.0, 3.2, 1.6, "flights", ["PK: дата, перевозчик, рейс,", "откуда, куда, время по плану",
                                                 "задержки, отмены, причины", "is_manual, is_deleted, file_id"], "proc")
    t("weather_obs", 5.4, 3.2, 3.2, 1.3, "weather_obs", ["PK: station, время", "ветер, видимость, облака,",
                                                         "явления, категория FAA"], "proc")
    t("forecast_weather", 5.4, 1.5, 3.2, 1.1, "forecast_weather", ["PK: station, час", "осадки, снег, порывы"], "proc")
    t("daily", 9.0, 3.4, 2.8, 2.2, "daily (витрина)", ["PK: дата", "вылеты, отмены,", "доля задержек,",
                                                         "минуты по причинам,", "погода ORD и сети"], "out")
    t("pred", 11.9, 4.9, 2.0, 1.3, "predictions", ["PK: дата, цель,", "версия модели"], "out")
    t("bt", 11.9, 3.2, 2.0, 1.1, "backtest", ["прогноз vs факт"], "out")
    t("runs", 11.9, 1.6, 2.0, 1.1, "model_runs", ["метрики, важность"], "out")
    d.box("log", 9.0, 0.7, 3.4, 0.9, "load_log · dq_log · edit_log\nwatermarks", "dec", size=8.5, diamond=False)
    d.arrow("raw_files", "flights", "file_id", ldy=0.05)
    d.arrow("raw_metar", "weather_obs", "разбор", ldy=0.05)
    d.arrow("raw_forecast", "forecast_weather")
    d.arrow("flights", "daily")
    d.arrow("weather_obs", "daily")
    d.arrow("forecast_weather", "daily")
    d.arrow("daily", "pred")
    d.arrow("daily", "bt")
    d.save("diagram_data_model.png")


def ingest_algorithm():
    d = Diagram(12, 8.6)
    d.box("start", 3.0, 8.1, 3.0, 0.6, "Запуск шага загрузки", "out", bold=True)
    d.box("lock", 3.0, 7.15, 2.6, 0.9, "Тот же шаг\nуже выполняется?", "dec", size=9)
    d.box("skip", 7.2, 7.15, 2.6, 0.6, "Журнал: «пропущен»", "bad")
    d.box("wm", 3.0, 6.05, 3.6, 0.75, "Прочитать отметку загрузки,\nопределить недостающий период", "proc")
    d.box("req", 3.0, 5.0, 3.6, 0.7, "HTTP-запрос с таймаутом", "proc")
    d.box("code", 3.0, 3.9, 2.8, 1.0, "Ответ?", "dec")
    d.box("retry", 7.2, 3.9, 3.2, 1.0, "429 / 5xx / таймаут:\nпауза 2, 4, 8 с\n(или Retry-After)", "dec", size=9)
    d.box("fail", 10.4, 3.9, 2.4, 0.9, "4 попытки исчерпаны:\nжурнал «ошибка»", "bad", size=9)
    d.box("valid", 3.0, 2.7, 3.6, 0.75, "Проверить формат\n(ZIP, CSV, поля JSON)", "proc")
    d.box("quar", 7.2, 2.7, 3.2, 0.75, "Битый файл → карантин,\nжурнал «ошибка»", "bad", size=9)
    d.box("tx", 3.0, 1.55, 3.6, 0.95, "Одна транзакция: вставка по ключу\n(ручные правки не трогать)\n+ сдвиг отметки загрузки", "proc", size=9)
    d.box("log", 3.0, 0.4, 3.6, 0.6, "Журнал: новых / обновлено / пропущено", "out")
    d.arrow("start", "lock")
    d.arrow("lock", "skip", "да", lpos=0.45)
    d.arrow("lock", "wm", "нет", ldx=0.25, ldy=-0.05)
    d.arrow("wm", "req")
    d.arrow("req", "code")
    d.arrow("code", "retry", "ошибка", lpos=0.45)
    d.arrow("retry", "req", "повтор", rad=0.3, lpos=0.5, ldy=0.1)
    d.arrow("retry", "fail", "нет попыток", lpos=0.5, ldy=0.45)
    d.arrow("code", "valid", "200", ldx=0.25, ldy=-0.05)
    d.arrow("valid", "quar", "не так", lpos=0.45)
    d.arrow("valid", "tx", "ок", ldx=0.2, ldy=-0.05)
    d.arrow("tx", "log")
    d.save("diagram_ingest.png")


def forecast_algorithm():
    d = Diagram(12, 7.4)
    d.box("mart", 2.4, 6.8, 4.0, 0.7, "Витрина daily: факт по дням + погода", "out", bold=True)
    d.box("feat", 2.4, 5.6, 4.0, 1.2, "Признаки дня:\nкалендарь и праздники · погода ORD ·\nпогода сети (по доле рейсов) ·\nчисло вылетов год назад", "proc", size=9)
    d.box("loop", 2.4, 4.15, 4.0, 1.0, "Для каждого из 6 последних месяцев:\nобучение только на данных до него", "proc", size=9)
    d.box("pred", 2.4, 2.85, 4.0, 0.8, "Прогноз месяца, сравнение\nс фактом и с нормой", "proc", size=9)
    d.box("metr", 2.4, 1.65, 4.0, 0.8, "MAE, MAPE; интервал 10–90%\nпо ошибкам остальных месяцев", "proc", size=9)
    d.box("cmp", 2.4, 0.5, 4.0, 0.75, "Сравнение: норма · линейная ·\nбустинг без сети · бустинг с сетью", "dec", size=8.5)
    d.box("final", 8.6, 5.6, 4.2, 0.9, "Финальная модель:\nобучение на всей истории", "proc")
    d.box("days", 8.6, 4.2, 4.2, 1.2, "Дни без факта BTS:\nпрошедшие — погода по METAR,\nбудущие — прогноз Open-Meteo", "proc", size=9)
    d.box("out", 8.6, 2.8, 4.2, 0.9, "Прогноз + интервал + норма\n→ predictions", "out")
    d.box("ui", 8.6, 1.5, 4.2, 0.9, "Дашборд: дни выше нормы\n→ решение о резерве", "out")
    d.arrow("mart", "feat")
    d.arrow("feat", "loop")
    d.arrow("loop", "pred")
    d.arrow("pred", "metr")
    d.arrow("metr", "cmp")
    d.arrow("feat", "final")
    d.arrow("final", "days")
    d.arrow("days", "out")
    d.arrow("metr", "out", "ширина интервала", lpos=0.5, ldy=0.1)
    d.arrow("out", "ui")
    d.save("diagram_forecast.png")


if __name__ == "__main__":
    architecture()
    data_model()
    ingest_algorithm()
    forecast_algorithm()
    print("ok:", sorted(p.name for p in OUT.glob("diagram_*.png")))
