"""Страница «Погода и задержки» (часть B).
Связывает слабоструктурированные METAR-сводки с задержками рейсов: каждый вылет сопоставляется
с погодой в аэропорту в час вылета.
"""
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
import ui
from db import connect

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

ui.page_header("Погода и задержки",
               f"Как погода в аэропорту {config.AIRPORT_IATA} влияет на пунктуальность вылетов. "
               "Погода — из METAR-сводок (текстовые наблюдения метеостанции аэропорта), задержки — из BTS.")


@st.cache_data(ttl=3600, show_spinner="Сопоставляю вылеты с погодой…")
def flights_with_weather(d0: str, d1: str) -> pd.DataFrame:
    """Каждому вылету — последняя METAR-сводка не старше 90 минут до планового времени вылета."""
    with connect() as con:
        f = pd.read_sql("""SELECT flight_date, crs_dep_time, dep_del15 FROM flights
                           WHERE direction = 'departure' AND is_deleted = 0 AND cancelled = 0
                             AND dep_del15 IS NOT NULL AND flight_date BETWEEN ? AND ?""", con, params=(d0, d1))
        w = pd.read_sql("""SELECT observed_at_utc, flight_cat, gust_kt, wind_kt, vis_sm, rain, snow, fzra, ts, fog, precip
                           FROM weather_obs WHERE parse_ok = 1""", con)
    hhmm = f["crs_dep_time"].clip(upper=2359)
    local = pd.to_datetime(f["flight_date"]) + pd.to_timedelta(hhmm // 100, "h") + pd.to_timedelta(hhmm % 100, "m")
    f["t"] = local.dt.tz_localize(config.AIRPORT_TZ, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    f["hour"], f["dow"] = local.dt.hour, local.dt.day_of_week
    f = f.dropna(subset=["t"]).sort_values("t")
    w["t"] = pd.to_datetime(w["observed_at_utc"], utc=True)
    w = w.sort_values("t")
    return pd.merge_asof(f, w, on="t", direction="backward", tolerance=pd.Timedelta(minutes=90))


bounds = ui.q("SELECT min(date) a, max(date) b FROM daily WHERE dep_flown IS NOT NULL")
lo, hi = date.fromisoformat(bounds.a[0]), date.fromisoformat(bounds.b[0])

# ---------- 1. Погода на неделю ----------
ui.question("Какая погода ожидается на неделе и чем она опасна для вылетов?",
            "Прогноз Open-Meteo по часам. Пунктир — пороги, после которых, по истории, задержек заметно больше.")
fc = ui.q("SELECT * FROM forecast_weather WHERE time_utc >= ? ORDER BY time_utc",
          (pd.Timestamp.now(tz="UTC").floor("h").strftime("%Y-%m-%dT%H:%M:%SZ"),))
if fc.empty:
    st.info("Прогноза погоды пока нет — запустите загрузку на странице «Журнал и качество».")
else:
    fc["t"] = pd.to_datetime(fc["time_utc"]).dt.tz_convert(config.AIRPORT_TZ)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        subplot_titles=("Порывы ветра, узлы", "Осадки, мм/ч", "Видимость, мили"))
    fig.add_trace(go.Scatter(x=fc.t, y=fc.gust_kt, line=dict(color=ui.SERIES[0], width=2), name="Порывы",
                             hovertemplate="%{x|%a %d.%m %H:%M}: %{y:.0f} уз<extra></extra>"), 1, 1)
    fig.add_hline(y=30, line=dict(color=ui.STATUS["serious"], dash="dot", width=1.5), row=1, col=1)
    snow = fc.snow_cm.fillna(0) > 0
    fig.add_trace(go.Bar(x=fc.t, y=fc.precip_mm, name="Осадки",
                         marker_color=np.where(snow, ui.SERIES[6], ui.SERIES[2]),
                         customdata=np.where(snow, "снег", "дождь"),
                         hovertemplate="%{x|%a %d.%m %H:%M}: %{y:.1f} мм (%{customdata})<extra></extra>"), 2, 1)
    fig.add_trace(go.Scatter(x=fc.t, y=fc.vis_sm.clip(upper=10), line=dict(color=ui.SERIES[3], width=2),
                             name="Видимость", hovertemplate="%{x|%a %d.%m %H:%M}: %{y:.1f} миль<extra></extra>"), 3, 1)
    fig.add_hline(y=3, line=dict(color=ui.STATUS["serious"], dash="dot", width=1.5), row=3, col=1)
    fig.update_layout(showlegend=False, hovermode="x")
    fig.update_xaxes(tickformat="%d.%m", dtick=86400000)
    fig.update_annotations(font=dict(size=12, color=ui.MUTED), x=0, xanchor="left")
    ui.chart(fig, 420)
    st.caption("Цвет осадков: зелёный — дождь, фиолетовый — снег. Пороги: порывы 30 узлов, видимость 3 мили (граница IFR).")

st.divider()
c0, c1 = st.columns([2, 3])
period = c0.date_input("Период истории для анализа", (lo, hi), min_value=lo, max_value=hi, format="DD.MM.YYYY")
if not isinstance(period, tuple) or len(period) != 2:
    st.stop()
d0, d1 = (p.isoformat() for p in period)
fw = flights_with_weather(d0, d1)
avg = fw["dep_del15"].mean()
c1.metric("Доля задержанных вылетов за период", ui.pct(avg), help=f"{len(fw):,} вылетов".replace(",", " "))


def share_bar(groups: dict, title_x: str, ordinal: bool = False):
    rows = [(name, fw.loc[mask, "dep_del15"].mean(), int(mask.sum())) for name, mask in groups.items()]
    df = pd.DataFrame(rows, columns=["cat", "share", "n"]).dropna()
    if not ordinal:
        df = df.sort_values("share")
    colors = ui.SEQ_BLUE[2:2 + len(df)] if ordinal else [ui.BLUE] * len(df)
    fig = go.Figure(go.Bar(
        x=df.share, y=df.cat, orientation="h", marker_color=colors, marker_cornerradius=4,
        text=[f"{s:.0%} · {n:,} выл.".replace(",", " ") for s, n in zip(df.share, df.n)], textposition="outside",
        textfont=dict(color=ui.INK2), cliponaxis=False,
        hovertemplate="%{y}: %{x:.1%} задержано<extra></extra>"))
    fig.add_vline(x=avg, line=dict(color=ui.NORM, dash="dash", width=1.5))
    fig.update_xaxes(tickformat=".0%", title=title_x, range=[0, max(df.share.max() * 1.3, 0.1)])
    fig.update_yaxes(autorange="reversed" if ordinal else True)
    return fig


# ---------- 2. Какие условия бьют сильнее ----------
ui.question("Какие погодные условия сильнее всего бьют по пунктуальности?",
            f"Каждый вылет сопоставлен с METAR-сводкой на момент вылета. Пунктир — средняя доля задержек ({avg:.0%}).")
a, b = st.columns(2)
with a:
    st.markdown("**По категории полётных условий**")
    cats = {"VFR — хорошие": "VFR", "MVFR — сложные": "MVFR", "IFR — по приборам": "IFR", "LIFR — очень плохие": "LIFR"}
    ui.chart(share_bar({k: fw.flight_cat == v for k, v in cats.items()}, "доля задержанных вылетов", ordinal=True), 300)
    st.caption("Категории FAA по видимости и нижней границе облаков: VFR > 5 миль и > 3000 футов, LIFR < 1 мили или < 500 футов.")
with b:
    st.markdown("**По погодным явлениям**")
    gust = fw.gust_kt.fillna(fw.wind_kt)
    calm = (fw.precip == 0) & (fw.fog == 0) & (fw.ts == 0) & (gust < 30)
    ui.chart(share_bar({
        "Без явлений": calm, "Дождь": (fw.rain == 1) & (fw.snow == 0), "Снег": fw.snow == 1,
        "Ледяной дождь": fw.fzra == 1, "Гроза": fw.ts == 1, "Туман": fw.fog == 1, "Порывы ≥ 30 уз": gust >= 30,
    }, "доля задержанных вылетов"), 300)
    st.caption("Категории пересекаются: вылет при грозе с дождём учтён и в «Грозе», и в «Дожде».")

st.divider()
a, b = st.columns(2)

# ---------- 3. Причины ----------
with a:
    ui.question("Из-за чего возникают задержки?",
                "Минуты задержки вылетов по причинам, которые указывают перевозчики (BTS).")
    dly = ui.q(f"""SELECT substr(date,1,7) m, {', '.join(f'sum({c}) {c}' for c in ui.CAUSES)}
                   FROM daily WHERE date BETWEEN ? AND ? AND dep_flown IS NOT NULL GROUP BY 1 ORDER BY 1""", (d0, d1))
    fig = go.Figure()
    for i, (col, name) in enumerate(ui.CAUSES.items()):
        fig.add_trace(go.Bar(x=dly.m, y=dly[col] / 1000, name=name, marker_color=ui.SERIES[i],
                             marker_line=dict(color=ui.SURFACE, width=1),
                             hovertemplate=f"{name}: %{{y:.0f}} тыс. мин<extra></extra>"))
    fig.update_layout(barmode="stack", hovermode="x unified", legend=dict(font_size=11, traceorder="normal"))
    fig.update_yaxes(title="тыс. минут задержки")
    ui.chart(fig, 360)
    tot = dly[list(ui.CAUSES)].sum()
    st.caption(f"«Погода» в отчётности перевозчиков — лишь {tot.min_weather / tot.sum():.0%} минут: "
               "задержки из-за погоды часто записываются в «Авиасистему (NAS)» или «Поздний прилёт».")

# ---------- 4. Часы и дни недели ----------
with b:
    ui.question("В какие часы и дни недели задержки хуже всего?",
                "Доля задержанных вылетов по плановому часу вылета (местное время) и дню недели.")
    hm = fw[(fw.hour >= 5)].pivot_table(index="dow", columns="hour", values="dep_del15", aggfunc=["mean", "size"])
    share, n = hm["mean"], hm["size"]
    fig = go.Figure(go.Heatmap(
        z=share.values, x=[f"{h:02d}" for h in share.columns], y=[WD[d] for d in share.index],
        colorscale=[[i / (len(ui.SEQ_BLUE) - 1), c] for i, c in enumerate(ui.SEQ_BLUE)],
        xgap=2, ygap=2, customdata=n.values, colorbar=dict(tickformat=".0%", thickness=10),
        hovertemplate="%{y}, %{x}:00 — задержано %{z:.0%} (вылетов: %{customdata})<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="час планового вылета")
    ui.chart(fig, 360)
    st.caption("Ночные часы до 05:00 скрыты — там единицы рейсов. К вечеру задержки накапливаются по цепочке.")
