"""Страница «Журнал и качество» (часть A): запуск обработки, журнал загрузок, схема пайплайна, проверки качества."""
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dq
import pipeline
import ui

LABEL = {"success": "успешно", "partial": "частично", "failed": "ошибка", "skipped": "пропущен",
         "running": "выполняется"}
COLOR = {"success": ui.STATUS["good"], "partial": ui.STATUS["warning"], "failed": ui.STATUS["critical"],
         "skipped": ui.MUTED, "running": ui.BLUE}
JOB_NAMES = {"bts": "BTS: рейсы", "bts_import": "BTS: ручной импорт", "metar": "METAR: погода",
             "metar_network": "METAR: аэропорты сети",
             "openmeteo": "Open-Meteo: прогноз", "weather_transform": "Разбор METAR", "marts": "Витрина",
             "model": "Модель", "dq": "Проверки качества"}
FAULTS = {"none": "без сбоев", "timeout": "таймаут источников", "rate_limit_429": "лимит запросов (429)",
          "corrupt_bts_file": "битый файл BTS (перекачка месяца ~2 мин)"}

ui.page_header("Журнал загрузок и качество данных",
               "Загрузка инкрементальная (догружается только новое) и идемпотентная (повтор ничего не задваивает). "
               "Каждый запуск записывается в журнал.")

marks = ui.q("SELECT source, value FROM watermarks")
marks = dict(zip(marks.source, marks.value))

# ---------- Запуск ----------
c1, c2, _ = st.columns([1.4, 1.6, 3])
fault = c2.selectbox("Демо-режим сбоев", list(FAULTS), format_func=FAULTS.get,
                     help="Для демонстрации устойчивости: источники «падают», система ретраит, пишет ошибку в журнал "
                          "и продолжает остальные шаги.")
if c1.button("Обновить данные сейчас", type="primary", icon=":material/sync:"):
    os.environ["AERO_FAULT"] = fault
    try:
        with st.status("Выполняю цепочку обработки…", expanded=True) as box:
            results = []
            for name, fn in pipeline.jobs().items():
                st.write(f"{JOB_NAMES.get(name, name)}…")
                if name == "bts" and fault == "corrupt_bts_file":
                    # новых месяцев может не быть — для демо перекачиваем последний загруженный месяц
                    r = fn(trigger="manual", month=marks.get("bts"))
                else:
                    r = fn(trigger="manual")
                results.append(r)
                s = r.stats
                st.write(f"**{LABEL[r.status]}**: новых {s['rows_inserted']}, обновлено {s['rows_updated']}, "
                         f"пропущено {s['rows_skipped']}, ретраев {s['retries']}" + (f" — {r.error}" if r.error else ""))
            worst = "failed" if any(r.status == "failed" for r in results) else \
                "partial" if any(r.status != "success" for r in results) else "success"
            box.update(label=f"Готово: {LABEL[worst]}", state="error" if worst == "failed" else "complete")
    finally:
        os.environ["AERO_FAULT"] = "none"
    ui.refresh()

# ---------- Свежесть ----------
last = ui.q("""SELECT job, max(finished_at) t FROM load_log WHERE status IN ('success','partial') GROUP BY job""")
last = dict(zip(last.job, last.t))
cols = st.columns(3)
for col, (src, label, wm_label) in zip(cols, [("bts", "BTS — рейсы", "последний загруженный месяц"),
                                              ("metar", "METAR — погода", "последняя сводка, UTC"),
                                              ("openmeteo", "Open-Meteo — прогноз", "начало прогноза, UTC")]):
    t = last.get(src)
    ago = "никогда" if t is None else f"{(pd.Timestamp.now(tz='UTC') - pd.Timestamp(t)).total_seconds() / 3600:.1f} ч назад"
    value = marks.get(src, "—")
    if src != "bts" and value != "—":  # 2026-11-16T00:00:00Z -> 16.11.2026 00:00
        ts = pd.Timestamp(value)
        value = ts.strftime("%d.%m.%Y %H:%M")
    col.metric(label, value, help=wm_label)
    col.caption(f"{wm_label} · обновлялся {ago}")

st.divider()

# ---------- Схема пайплайна ----------
ui.question("Где в цепочке обработки проблема, если она есть?",
            "Статус последнего запуска каждого шага: источники → сырые данные → очищенные → витрина → модель.")
st_last = ui.q("""SELECT l.job, l.status FROM load_log l
                  JOIN (SELECT job, max(id) id FROM load_log GROUP BY job) m ON m.id = l.id""")
s = dict(zip(st_last.job, st_last.status))


def node(name, label, job=None):
    color = COLOR.get(s.get(job), ui.AXIS) if job else ui.AXIS
    return f'{name} [label="{label}", color="{color}", penwidth=2.5];'


dot = f"""digraph {{ rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded", fontname="Segoe UI", fontsize=11];
  {node('s1', 'BTS\\n(ZIP/CSV)', 'bts')} {node('s2', 'IEM METAR\\n(текст)', 'metar')} {node('s3', 'Open-Meteo\\n(JSON)', 'openmeteo')}
  {node('r1', 'raw_files\\n+ ZIP на диске')} {node('r2', 'raw_metar')} {node('r3', 'raw_forecast')}
  {node('c1', 'flights', 'bts')} {node('c2', 'weather_obs', 'weather_transform')} {node('c3', 'forecast_weather', 'openmeteo')}
  {node('m', 'daily\\n(витрина)', 'marts')} {node('ml', 'модель\\n+ backtest', 'model')} {node('q', 'проверки\\nкачества', 'dq')}
  {node('ui', 'дашборд')}
  s1 -> r1 -> c1 -> m; s2 -> r2 -> c2 -> m; s3 -> r3 -> c3 -> m; m -> ml -> ui; m -> ui;
  c1 -> q [style=dashed]; c2 -> q [style=dashed]; c3 -> q [style=dashed];
}}"""
st.graphviz_chart(dot, width="stretch")
st.caption("Рамка: зелёная — успешно, жёлтая — частично, красная — ошибка, серая — нет данных о запуске.")

st.divider()

# ---------- Журнал ----------
ui.question("Когда и чем закончились последние загрузки?",
            "Каждая точка — запуск. Наведите, чтобы увидеть счётчики и ошибку.")
log = ui.q("SELECT * FROM load_log ORDER BY id DESC LIMIT 500")
log["job_name"] = log.job.map(lambda j: JOB_NAMES.get(j, j))
log["t"] = pd.to_datetime(log.started_at)
fig = go.Figure()
for status, g in log.groupby("status"):
    fig.add_trace(go.Scatter(
        x=g.t, y=g.job_name, mode="markers", name=LABEL.get(status, status),
        marker=dict(size=11, color=COLOR.get(status, ui.MUTED), line=dict(color=ui.SURFACE, width=2)),
        customdata=g[["rows_inserted", "rows_skipped", "retries", "error"]].fillna("").values,
        hovertemplate="%{y} · %{x|%d.%m %H:%M}<br>новых %{customdata[0]}, пропущено %{customdata[1]}, "
                      "ретраев %{customdata[2]}<br>%{customdata[3]}<extra></extra>"))
fig.update_yaxes(categoryorder="array", categoryarray=list(JOB_NAMES.values())[::-1])
ui.chart(fig, 320)

show = log.assign(status=log.status.map(lambda x: LABEL.get(x, x))).fillna("")[
    ["id", "job_name", "trigger", "started_at", "status", "rows_fetched", "rows_inserted", "rows_updated",
     "rows_skipped", "http_calls", "retries", "watermark_before", "watermark_after", "error"]]
TEXT_COLOR = {LABEL[k]: v for k, v in COLOR.items()} | {"OK": ui.STATUS["good"], "внимание": "#b7791f"}


def paint(table, col="Статус"):
    """Статус — словом и цветом текста (вместо значков)."""
    return table.style.map(lambda v: f"color: {TEXT_COLOR.get(v, ui.INK2)}; font-weight: 600", subset=[col])


st.dataframe(paint(show.rename(columns={"id": "№", "job_name": "Шаг", "trigger": "Запуск", "started_at": "Начало (UTC)",
                                  "status": "Статус", "rows_fetched": "Получено", "rows_inserted": "Новых",
                                  "rows_updated": "Обновлено", "rows_skipped": "Пропущено", "http_calls": "HTTP",
                                  "retries": "Ретраи", "watermark_before": "Watermark до",
                                  "watermark_after": "Watermark после", "error": "Ошибка / замечание"})),
             hide_index=True, width="stretch", height=300)

st.divider()

# ---------- Качество ----------
ui.question("Можно ли доверять данным?",
            "Результаты последней проверки качества. error — данные некорректны, warning — подозрительно.")
res = ui.q("SELECT * FROM dq_log WHERE run_id = (SELECT max(run_id) FROM dq_log)")
if res.empty:
    st.info("Проверки ещё не запускались.")
else:
    res["ok"] = res.failed == 0
    res["Статус"] = [("OK" if ok else ("ошибка" if sev == "error" else "внимание"))
                     for ok, sev in zip(res.ok, res.severity)]
    res["Правило"] = res.rule.map(lambda r: dq.RULE_DESCRIPTIONS.get(r, r))
    res["Доля"] = [f"{f / c:.3%}" if c else "—" for f, c in zip(res.failed, res.checked)]
    st.dataframe(paint(res[["Статус", "Правило", "severity", "checked", "failed", "Доля"]].rename(
        columns={"severity": "Важность", "checked": "Проверено", "failed": "Не прошло"})),
        hide_index=True, width="stretch")
    bad = res[~res.ok]
    if not bad.empty:
        pick = st.selectbox("Показать примеры по правилу", bad.Правило.tolist())
        sample = json.loads(bad.set_index("Правило").loc[pick, "sample"] or "[]")
        st.code("\n".join(map(str, sample)) or "—")
    trend = ui.q("""SELECT d.run_id, l.started_at, sum(d.failed > 0) failed_rules, count(*) rules
                    FROM dq_log d JOIN load_log l ON l.id = d.run_id GROUP BY d.run_id ORDER BY d.run_id""")
    st.caption(f"Запусков проверки: {len(trend)}; в последнем не прошло правил: "
               f"{int(trend.failed_rules.iloc[-1])} из {int(trend.rules.iloc[-1])}.")
