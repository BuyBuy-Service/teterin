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
import marts
import ui
from db import connect

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

ui.page_header("Погода и задержки",
               f"Как погода в аэропорту {config.AIRPORT_IATA} влияет на пунктуальность вылетов. "
               "Погода — из METAR-сводок (текстовые наблюдения метеостанции аэропорта), задержки — из BTS.")


@st.cache_data(ttl=3600, show_spinner="Сопоставляю вылеты с погодой…")
def flights_with_weather(d0: str, d1: str) -> pd.DataFrame:
    with connect() as con:
        return marts.flights_with_weather(con, d0, d1)


bounds = ui.q("SELECT min(date) a, max(date) b FROM daily WHERE dep_flown IS NOT NULL")
lo, hi = date.fromisoformat(bounds.a[0]), date.fromisoformat(bounds.b[0])

# ---------- 1. Погода на неделю ----------
ui.question("Какая погода ожидается на неделе и чем она опасна для вылетов?",
            "Прогноз Open-Meteo по часам. Пунктир — пороги, после которых, по истории, задержек заметно больше.")
fc = ui.q("SELECT * FROM forecast_weather WHERE station = ? AND time_utc >= ? ORDER BY time_utc",
          (config.AIRPORT_IATA, pd.Timestamp.now(tz="UTC").floor("h").strftime("%Y-%m-%dT%H:%M:%SZ")))
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

# ---------- 2. Сеть ----------
ui.question("В каких аэропортах назначения на неделе ждать непогоду?",
            "10 аэропортов, куда из ORD летает больше всего рейсов. Непогода там тоже задерживает вылеты из Чикаго: "
            "рейсы держат на земле, пока не освободится аэропорт прибытия.")
today_local = pd.Timestamp.now(tz=config.AIRPORT_TZ).strftime("%Y-%m-%d")
with connect() as con:
    nd = marts.forecast_daily(con, sorted(config.NETWORK))
    share = pd.read_sql(f"""SELECT dest, count(*) n FROM flights WHERE direction='departure' AND is_deleted = 0
                            GROUP BY dest""", con).set_index("dest")["n"]
nd = nd[nd["date"] >= today_local]
if nd.empty:
    st.info("Прогноза для аэропортов сети пока нет.")
else:
    def why(r):
        out = []
        if r.w_ts: out.append("гроза")
        if r.w_fzra: out.append("ледяной дождь")
        if r.w_snow: out.append("снег")
        if r.w_lowvis_hours >= 3: out.append(f"плохая видимость {r.w_lowvis_hours:.0f} ч")
        if r.w_max_gust >= 35: out.append(f"порывы {r.w_max_gust:.0f} уз")
        return ", ".join(out)
    nd["why"] = [why(r) for r in nd.itertuples()]
    nd["severe"] = (nd["why"] != "").astype(int)
    total = share.sum()
    order = sorted(config.NETWORK, key=lambda s_: -share.get(s_, 0))
    days = sorted(nd["date"].unique())
    z = nd.pivot(index="station", columns="date", values="severe").reindex(index=order, columns=days)
    txt = nd.pivot(index="station", columns="date", values="why").reindex(index=order, columns=days).fillna("")
    labels = [f"{ui.CITY.get(s_, s_)} · {share.get(s_, 0) / total:.1%}" for s_ in order]
    xl = [f"{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][pd.Timestamp(d).weekday()]} {pd.Timestamp(d):%d.%m}" for d in days]
    fig = go.Figure(go.Heatmap(z=z.values, x=xl, y=labels, customdata=txt.values, zmin=0, zmax=1, showscale=False,
                               colorscale=[[0, "#eef1f6"], [1, ui.STATUS["serious"]]], xgap=3, ygap=3,
                               hovertemplate="%{y}, %{x}: %{customdata}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig, 380)
    st.caption("Оранжевая клетка — в этот день ожидается гроза, ледяной дождь, снег, ≥ 3 ч плохой видимости или "
               "порывы ≥ 35 узлов. Процент — доля вылетов из ORD в этот аэропорт.")

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
groups = marts.weather_groups(fw)
a, b = st.columns(2)
with a:
    st.markdown("**По категории полётных условий**")
    ui.chart(share_bar(groups["categories"], "доля задержанных вылетов", ordinal=True), 300)
    st.caption("Категории FAA по видимости и нижней границе облаков: VFR > 5 миль и > 3000 футов, LIFR < 1 мили или < 500 футов.")
with b:
    st.markdown("**По погодным явлениям**")
    ui.chart(share_bar(groups["phenomena"], "доля задержанных вылетов"), 300)
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
