"""Страница «Данные» (часть A): просмотр, фильтры, правка и удаление рейсов, импорт и экспорт."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import config
import edits
import marts
import model
import ui
from sources import bts

ui.page_header("Данные о рейсах",
               "Рейсы аэропорта из BTS. Правки и удаления сохраняются с автором в журнале правок и "
               "не перезаписываются при повторной загрузке источника.")

user = st.sidebar.selectbox("Кто вносит правки", ui.USERS)
EDIT_COLS = list(edits.EDITABLE)
LIMIT = 2000

bounds = ui.q("SELECT min(flight_date) a, max(flight_date) b FROM flights")
if bounds.a[0] is None:
    st.info("Рейсов пока нет — загрузите BTS на странице «Журнал и качество» или импортируйте ZIP ниже.")
else:
    lo, hi = date.fromisoformat(bounds.a[0]), date.fromisoformat(bounds.b[0])
    f1, f2, f3, f4, f5 = st.columns([2.2, 1.2, 1.6, 1.6, 1.2])
    period = f1.date_input("Даты", (hi - timedelta(days=2), hi), min_value=lo, max_value=hi, format="DD.MM.YYYY")
    direction = f2.selectbox("Направление", ["все", "вылет", "прилёт"])
    carriers = ui.q("SELECT DISTINCT carrier FROM flights ORDER BY 1").carrier.tolist()
    carrier = f3.multiselect("Перевозчик", carriers, placeholder="все")
    status = f4.selectbox("Статус", ["все", "задержанные ≥15 мин", "отменённые", "изменённые вручную", "удалённые"])
    flight_no = f5.text_input("Номер рейса", placeholder="напр. 1234")
    if not isinstance(period, tuple) or len(period) != 2:
        st.stop()

    where, params = ["f.flight_date BETWEEN ? AND ?"], [period[0].isoformat(), period[1].isoformat()]
    if direction != "все":
        where.append("f.direction = ?")
        params.append("departure" if direction == "вылет" else "arrival")
    if carrier:
        where.append(f"f.carrier IN ({','.join('?' * len(carrier))})")
        params += carrier
    where.append("f.is_deleted = 1" if status == "удалённые" else "f.is_deleted = 0")
    where += {"задержанные ≥15 мин": ["f.dep_del15 = 1"], "отменённые": ["f.cancelled = 1"],
              "изменённые вручную": ["f.is_manual = 1"]}.get(status, [])
    if flight_no.strip().isdigit():
        where.append("f.flight_number = ?")
        params.append(int(flight_no))
    sql_where = " AND ".join(where)
    total = ui.q(f"SELECT count(*) n FROM flights f WHERE {sql_where}", tuple(params)).n[0]
    df = ui.q(f"""SELECT {', '.join('f.' + k for k in edits.KEY)},
                         CASE f.direction WHEN 'departure' THEN 'вылет' ELSE 'прилёт' END AS direction, {', '.join('f.' + c for c in EDIT_COLS)},
                         f.dep_del15, f.is_manual, f.tail_number, r.period || ' · ' || substr(r.sha256, 1, 8) AS source_file
                  FROM flights f LEFT JOIN raw_files r ON r.id = f.file_id
                  WHERE {sql_where} ORDER BY f.flight_date, f.crs_dep_time LIMIT {LIMIT}""", tuple(params))
    st.caption(f"Найдено {total:,} рейсов".replace(",", " ") + (f", показаны первые {LIMIT}" if total > LIMIT else ""))

    deleting = status == "удалённые"
    df.insert(0, "mark", False)
    labels = {
        "mark": "Восстановить" if deleting else "Удалить", "flight_date": "Дата", "carrier": "Авиакомпания",
        "flight_number": "Рейс", "origin": "Откуда", "dest": "Куда", "crs_dep_time": "Вылет по плану",
        "direction": "Направление", "dep_time": "Вылет факт", "dep_delay": "Задержка вылета, мин",
        "arr_time": "Прилёт факт", "arr_delay": "Задержка прилёта, мин", "cancelled": "Отменён", "diverted": "Ушёл на запасной",
        "carrier_delay": "Мин: перевозчик", "weather_delay": "Мин: погода", "nas_delay": "Мин: NAS",
        "security_delay": "Мин: безопасность", "late_aircraft_delay": "Мин: поздний самолёт",
        "dep_del15": "Задержан ≥15", "is_manual": "Правлен вручную", "tail_number": "Борт", "source_file": "Файл-источник",
    }
    cfg = {c: st.column_config.Column(labels.get(c, c)) for c in df.columns}
    cfg["mark"] = st.column_config.CheckboxColumn(labels["mark"])
    for c in ("cancelled", "diverted"):
        cfg[c] = st.column_config.CheckboxColumn(labels[c])
    for c in ("dep_del15", "is_manual"):
        cfg[c] = st.column_config.CheckboxColumn(labels[c], disabled=True)
    view = df.copy()
    for c in ("cancelled", "diverted", "dep_del15", "is_manual"):
        view[c] = view[c].fillna(0).astype(bool)
    edited = st.data_editor(view, column_config=cfg, hide_index=True, width="stretch", height=440,
                            disabled=[c for c in df.columns if c not in EDIT_COLS + ["mark"]], key="flights_editor")

    b1, b2, b3, _ = st.columns([1.3, 1.6, 1.3, 3])
    if b1.button("💾 Сохранить изменения", type="primary"):
        errors, n_fields, n_rows = [], 0, 0
        for i in range(len(view)):
            before, after = view.iloc[i], edited.iloc[i]
            key = {k: (int(before[k]) if k in ("flight_number", "crs_dep_time") else before[k]) for k in edits.KEY}
            changes = {c: (int(after[c]) if c in ("cancelled", "diverted") else after[c])
                       for c in EDIT_COLS if not (pd.isna(before[c]) and pd.isna(after[c])) and before[c] != after[c]}
            if changes:
                try:
                    n_fields += edits.update_flight(key, changes, user)
                    n_rows += 1
                except ValueError as e:
                    errors.append(f"{edits.row_key(key)}: {e}")
        keys = [{k: (int(r[k]) if k in ("flight_number", "crs_dep_time") else r[k]) for k in edits.KEY}
                for _, r in edited[edited["mark"]].iterrows()]
        n_del = edits.set_deleted(keys, not deleting, user) if keys else 0
        ui.refresh()
        msg = f"Изменено полей: {n_fields} в {n_rows} рейсах; {'восстановлено' if deleting else 'удалено'}: {n_del}."
        (st.warning if errors else st.success)(msg + ("\n\nОшибки:\n- " + "\n- ".join(errors) if errors else ""))
    if b2.button("🔄 Пересчитать витрину и прогноз"):
        with st.spinner("Пересобираю витрину и переобучаю модель…"):
            r1, r2 = marts.build(), model.train_and_predict()
        ui.refresh()
        st.success(f"Витрина: {r1.status}, модель: {r2.status}")
    b3.download_button("⬇️ Выгрузить CSV", df.drop(columns="mark").to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"flights_{period[0]}_{period[1]}.csv", mime="text/csv")

st.divider()
c1, c2 = st.columns(2)
with c1:
    st.markdown("#### Импорт файла BTS вручную")
    st.caption("Запасной путь, если сайт BTS недоступен из скрипта: скачайте ZIP с transtats.bts.gov в браузере "
               "и загрузите сюда. Повторный импорт того же файла ничего не задвоит.")
    up = st.file_uploader("ZIP-архив BTS On-Time Performance", type="zip")
    if up is not None and st.button("Импортировать"):
        dst = config.RAW_DIR / "upload" / Path(up.name).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(up.getvalue())
        with st.spinner("Импортирую…"):
            r = bts.import_file(path=str(dst))
        ui.refresh()
        s = r.stats
        (st.success if r.status == "success" else st.error)(
            f"{r.status}: новых {s['rows_inserted']}, обновлено {s['rows_updated']}, без изменений {s['rows_skipped']}"
            + (f" — {r.error}" if r.error else ""))
with c2:
    st.markdown("#### Журнал правок")
    log = ui.q("SELECT ts, user_name, row_key, field, old_value, new_value FROM edit_log ORDER BY id DESC LIMIT 200")
    st.dataframe(log.rename(columns={"ts": "Когда", "user_name": "Кто", "row_key": "Рейс", "field": "Поле",
                                     "old_value": "Было", "new_value": "Стало"}),
                 hide_index=True, width="stretch", height=300)
