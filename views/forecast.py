"""Страница «Прогноз» (часть C).
Пользователь — операционный менеджер аэропорта/перевозчика: нужен ли резерв персонала и стоек на ближайшие дни.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import ui

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
today = datetime.now(ZoneInfo(config.AIRPORT_TZ)).date()

ui.page_header("Прогноз задержек и рейсов",
               f"Аэропорт {config.AIRPORT_IATA}, вылеты. Прогноз строится по календарю и погоде дня; "
               "задержка — вылет позже расписания на 15 минут и больше (стандарт DOT).")

run = ui.q("SELECT * FROM model_runs ORDER BY trained_at DESC LIMIT 1")
if run.empty:
    st.warning("Модель ещё не обучалась — запустите обработку на странице «Журнал и качество».")
    st.stop()
version = run.model_version[0]
pred = ui.q("""SELECT p.*, d.w_max_gust, d.w_precip_hours, d.w_lowvis_hours, d.w_snow, d.w_ts, d.w_fzra, d.w_rain,
                      d.w_source
               FROM predictions p JOIN daily d ON d.date = p.target_date
               WHERE p.model_version = ? ORDER BY p.target_date""", (version,))
pred["date"] = pd.to_datetime(pred["target_date"])
week = pred[(pred["date"].dt.date >= today) & (pred["date"].dt.date <= today + timedelta(days=7))].copy()
week["label"] = [f"{WD[d.weekday()]} {d:%d.%m}" for d in week["date"]]
delay = week[week.target == "dep_del15_share"].reset_index(drop=True)
flown = week[week.target == "dep_flown"].reset_index(drop=True)


def risks(r) -> list[str]:
    out = []
    if r.w_ts: out.append("гроза")
    if r.w_fzra: out.append("ледяной дождь")
    if r.w_snow: out.append("снег")
    if r.w_max_gust and r.w_max_gust >= 30: out.append(f"порывы до {r.w_max_gust:.0f} уз")
    if r.w_lowvis_hours and r.w_lowvis_hours >= 3: out.append(f"плохая видимость {r.w_lowvis_hours:.0f} ч")
    if r.w_precip_hours and r.w_precip_hours >= 6 and not r.w_snow: out.append(f"осадки {r.w_precip_hours:.0f} ч")
    return out


# ---------- KPI ----------
last_month = ui.q("SELECT max(substr(date,1,7)) m FROM daily WHERE dep_flown IS NOT NULL").m[0]
ly_month = f"{int(last_month[:4]) - 1}{last_month[4:]}"
fact = ui.q("""SELECT substr(date,1,7) m, sum(dep_del15_share * dep_flown) / sum(dep_flown) share,
                      sum(dep_cancelled) * 1.0 / sum(dep_scheduled) canc, avg(dep_delay_mean) delay
               FROM daily WHERE substr(date,1,7) IN (?, ?) GROUP BY 1""", (last_month, ly_month)).set_index("m")

tomorrow = delay[delay.date.dt.date == today + timedelta(days=1)]
k1, k2, k3, k4 = st.columns(4)
if not tomorrow.empty:
    t = tomorrow.iloc[0]
    k1.metric("Задержки завтра (прогноз)", ui.pct(t.yhat),
              delta=f"{(t.yhat - t.baseline) * 100:+.1f} п.п. к норме", delta_color="inverse",
              help=f"Интервал 10–90%: {ui.pct(t.yhat_lo)} … {ui.pct(t.yhat_hi)}. Норма — {ui.pct(t.baseline)}.")
    tf = flown[flown.date.dt.date == today + timedelta(days=1)]
    if not tf.empty:
        k2.metric("Вылетов завтра (прогноз)", f"{tf.yhat.iloc[0]:,.0f}".replace(",", " "),
                  delta=f"{tf.yhat.iloc[0] - tf.baseline.iloc[0]:+,.0f} к прошлому году".replace(",", " "),
                  delta_color="off")
if last_month in fact.index:
    f, fl = fact.loc[last_month], fact.loc[ly_month] if ly_month in fact.index else None
    k3.metric(f"Задержки, факт {last_month}", ui.pct(f.share),
              delta=None if fl is None else f"{(f.share - fl.share) * 100:+.1f} п.п. к {ly_month}",
              delta_color="inverse", help="Последний месяц, опубликованный BTS (лаг публикации 2–3 мес.)")
    k4.metric(f"Отмены, факт {last_month}", ui.pct(f.canc, 1),
              delta=None if fl is None else f"{(f.canc - fl.canc) * 100:+.1f} п.п. к {ly_month}",
              delta_color="inverse")

st.divider()

# ---------- 1. Главный виджет ----------
ui.question("Какую долю задержек ждать в ближайшие 7 дней и выше ли она нормы?",
            "Норма — средняя доля задержек для этого дня недели и месяца по истории. "
            "Полоса — интервал, в который факт попадал ~8 дней из 10 на проверке.")
thr = st.slider("Считать день проблемным, если прогноз выше нормы хотя бы на (п.п.)", 0, 10, 3)
delay["above"] = (delay.yhat - delay.baseline) * 100 >= thr

fig = go.Figure()
fig.add_trace(go.Scatter(x=delay.label, y=delay.yhat_hi, mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
fig.add_trace(go.Scatter(x=delay.label, y=delay.yhat_lo, mode="lines", line=dict(width=0), fill="tonexty",
                         fillcolor="rgba(42,120,214,0.15)", name="Интервал 10–90%", hoverinfo="skip"))
fig.add_trace(go.Scatter(x=delay.label, y=delay.baseline, name="Норма", mode="lines",
                         line=dict(color=ui.NORM, width=2, dash="dash"),
                         hovertemplate="Норма: %{y:.0%}<extra></extra>"))
fig.add_trace(go.Scatter(
    x=delay.label, y=delay.yhat, name="Прогноз", mode="lines+markers", line=dict(color=ui.BLUE, width=2),
    marker=dict(size=[13 if a else 9 for a in delay.above],
                color=[ui.STATUS["serious"] if a else ui.BLUE for a in delay.above],
                symbol=["triangle-up" if a else "circle" for a in delay.above],
                line=dict(color=ui.SURFACE, width=2)),
    customdata=[[ui.pct(r.yhat_lo), ui.pct(r.yhat_hi), ", ".join(risks(r)) or "без опасных явлений",
                 "▲ выше нормы" if r.above else "в пределах нормы"] for r in delay.itertuples()],
    hovertemplate="<b>%{x}</b><br>Прогноз: %{y:.0%} (%{customdata[0]}…%{customdata[1]})<br>"
                  "%{customdata[3]}<br>Погода: %{customdata[2]}<extra></extra>"))
fig.update_yaxes(tickformat=".0%", rangemode="tozero", title="доля вылетов с задержкой ≥15 мин")
fig.update_layout(hovermode="x unified")
ui.chart(fig, 360)

bad = delay[delay.above]
if bad.empty:
    st.success(f"✅ Все дни в пределах нормы (порог +{thr} п.п.) — дополнительный резерв не нужен.")
else:
    lines = [f"- **{r.label}** — {ui.pct(r.yhat)} при норме {ui.pct(r.baseline)}"
             + (f"; причина: {', '.join(risks(r))}" if risks(r) else "") for r in bad.itertuples()]
    st.warning("⚠️ **Дни выше нормы — стоит заложить резерв персонала и стоек:**\n" + "\n".join(lines))

st.divider()
c1, c2 = st.columns(2)

# ---------- 2. Число рейсов ----------
with c1:
    ui.question("Сколько вылетов ожидается по дням?",
                "Столбец — прогноз, отрезок — интервал 10–90%, серая черта — тот же день недели год назад.")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=flown.label, y=flown.yhat, name="Прогноз", marker_color=ui.BLUE,
                         marker_cornerradius=4,
                         error_y=dict(type="data", symmetric=False, array=flown.yhat_hi - flown.yhat,
                                      arrayminus=flown.yhat - flown.yhat_lo, color=ui.MUTED, thickness=1.5),
                         hovertemplate="<b>%{x}</b><br>Прогноз: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=flown.label, y=flown.baseline, name="Год назад", mode="markers",
                             marker=dict(symbol="line-ew", size=26, line=dict(width=3, color=ui.NORM)),
                             hovertemplate="Год назад: %{y:,.0f}<extra></extra>"))
    fig.update_yaxes(rangemode="tozero", title="вылетов в день", separatethousands=True)
    ui.chart(fig, 320)

# ---------- 3. Точность ----------
with c2:
    ui.question("Насколько можно верить прогнозу?",
                "Проверка на истории: каждый месяц прогнозировался моделью, обученной только на прошлых данных.")
    tgt = st.radio("Показатель", ["dep_del15_share", "dep_flown"], horizontal=True, label_visibility="collapsed",
                   format_func={"dep_del15_share": "Доля задержек", "dep_flown": "Число вылетов"}.get)
    bt = ui.q("SELECT * FROM backtest WHERE model_version = ? AND target = ? ORDER BY date", (version, tgt))
    bt["date"] = pd.to_datetime(bt["date"])
    fmt = ".0%" if tgt == "dep_del15_share" else ",.0f"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bt.date, y=bt.actual, name="Факт", line=dict(color=ui.SERIES[0], width=2),
                             hovertemplate=f"Факт: %{{y:{fmt}}}<extra></extra>"))
    fig.add_trace(go.Scatter(x=bt.date, y=bt.yhat, name="Прогноз", line=dict(color=ui.SERIES[1], width=2),
                             hovertemplate=f"Прогноз: %{{y:{fmt}}}<extra></extra>"))
    fig.update_yaxes(tickformat=fmt, rangemode="tozero")
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
    fig.update_layout(hovermode="x unified")
    ui.chart(fig, 270)
    m = json.loads(run.metrics_json[0])[tgt]
    mm, mb = m["model"], m["baseline"]
    unit = (lambda v: f"{v * 100:.1f} п.п.") if tgt == "dep_del15_share" else (lambda v: f"{v:.0f} рейсов")
    st.markdown(
        f"Средняя ошибка (MAE): **модель {unit(mm['mae'])}**, норма {unit(mb['mae'])} — "
        f"модель точнее на **{(1 - mm['mae'] / mb['mae']) * 100:.0f}%**. "
        f"Факт попал в интервал в **{mm['coverage']:.0f}%** дней. Период проверки: {m['from']} — {m['to']}.")

# живая проверка: прогнозы, сделанные заранее, для дней, по которым BTS уже опубликовал факт
live = ui.q("""SELECT p.target_date, p.target, p.yhat, d.dep_del15_share, d.dep_flown, p.created_at
               FROM predictions p JOIN daily d ON d.date = p.target_date
               WHERE d.dep_flown IS NOT NULL AND p.created_at < p.target_date""")
with st.expander("Живая проверка: прогнозы, сделанные заранее, против опубликованного факта"):
    if live.empty:
        st.info("Пока нет: факт за дни, которые модель прогнозировала заранее, появится после публикации "
                "BTS за сентябрь 2026 (ожидается в конце ноября). После загрузки сравнение построится само.")
    else:
        live["actual"] = live.apply(lambda r: r[r.target], axis=1)
        st.dataframe(live.groupby("target").apply(
            lambda g: pd.Series({"дней": len(g), "MAE": (g.actual - g.yhat).abs().mean()})), width="stretch")

with st.expander("Что модель считает важным (permutation importance)"):
    imp = pd.Series(json.loads(run.importance_json[0])["dep_del15_share"]).sort_values()
    names = {"w_ts": "Гроза", "w_min_vis": "Мин. видимость", "w_max_gust": "Макс. порывы", "w_precip_hours": "Часы осадков",
             "w_lowvis_hours": "Часы плохой видимости", "w_snow": "Снег", "w_fzra": "Ледяной дождь", "w_fog": "Туман",
             "w_rain": "Дождь", "dow": "День недели", "month": "Месяц", "doy_sin": "Сезон (sin)", "doy_cos": "Сезон (cos)",
             "holiday_dist": "Близость праздника"}
    imp = imp[imp > 0]
    fig = go.Figure(go.Bar(x=imp.values * 100, y=[names.get(i, i) for i in imp.index], orientation="h",
                           marker_color=ui.BLUE, marker_cornerradius=4,
                           hovertemplate="%{y}: ошибка растёт на %{x:.2f} п.п., если признак перемешать<extra></extra>"))
    fig.update_xaxes(title="на сколько п.п. растёт ошибка без признака")
    ui.chart(fig, 300)
    st.caption(f"Модель {version}, обучена на {run.train_from[0]} — {run.train_to[0]}.")
