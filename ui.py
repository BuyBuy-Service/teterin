"""Общее оформление дашборда: цвета, шаблон графиков, заголовок-вопрос, доступ к БД."""
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from db import connect

# Палитра (проверенная на различимость при дальтонизме): категориальные цвета — в фиксированном порядке
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE = SERIES[0]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
NORM = "#898781"  # «норма» — нейтральный серый, чтобы не спорить с данными

pio.templates["aero"] = go.layout.Template(layout=dict(
    font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK2, size=13),
    paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, colorway=SERIES,
    xaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickcolor=AXIS, title_font_color=MUTED),
    yaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickcolor=AXIS, title_font_color=MUTED),
    hoverlabel=dict(bgcolor="white", font_color=INK, bordercolor=AXIS),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""),
    margin=dict(l=10, r=10, t=30, b=10), bargap=0.25,
    separators=", ",  # русский формат: 1 200 и 0,5
))
pio.templates.default = "aero"

CAUSES = {"min_carrier": "Перевозчик", "min_late_aircraft": "Поздний прилёт самолёта",
          "min_nas": "Авиасистема (NAS)", "min_weather": "Погода", "min_security": "Безопасность"}
USERS = ["Харлашкина А.В.", "Селиванова А.К.", "Козлов В.Н.", "гость"]


def question(text: str, why: str | None = None):
    """Каждый виджет дашборда начинается с вопроса пользователя, на который он отвечает."""
    st.markdown(f"#### {text}")
    if why:
        st.caption(why)


@st.cache_data(ttl=60, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql(sql, con, params=params)


def refresh():
    q.clear()


def pct(x, digits=0) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:.{digits}f}%"


def chart(fig, height=340):
    fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


def page_header(title: str, subtitle: str):
    st.title(title)
    st.caption(subtitle)
