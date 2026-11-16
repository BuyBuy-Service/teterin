"""AeroPulse — дашборд. Запуск: streamlit run app.py"""
import streamlit as st

import config
from db import init_db

st.set_page_config(page_title=f"AeroPulse · {config.AIRPORT_IATA}", page_icon="✈️", layout="wide")
init_db()

pages = {
    "Решения": [
        st.Page("views/forecast.py", title="Прогноз", icon="📈", default=True),   # часть C
        st.Page("views/weather.py", title="Погода и задержки", icon="🌦️"),       # часть B
    ],
    "Данные и процессы": [
        st.Page("views/data.py", title="Данные", icon="🗂️"),                      # часть A
        st.Page("views/ops.py", title="Журнал и качество", icon="🩺"),            # часть A
    ],
}
st.sidebar.markdown(f"**AeroPulse** · аэропорт {config.AIRPORT_IATA}")
st.navigation(pages).run()
