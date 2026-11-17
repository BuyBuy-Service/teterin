"""AeroPulse — дашборд. Запуск: streamlit run app.py"""
import streamlit as st

import config
from db import init_db

st.set_page_config(page_title=f"AeroPulse · {config.AIRPORT_IATA}", page_icon=":material/flight_takeoff:", layout="wide")
init_db()

pages = {
    "Решения": [
        st.Page("views/forecast.py", title="Прогноз", icon=":material/trending_up:", default=True),   # часть C
        st.Page("views/weather.py", title="Погода и задержки", icon=":material/thunderstorm:"),       # часть B
    ],
    "Данные и процессы": [
        st.Page("views/data.py", title="Данные", icon=":material/table_view:"),                      # часть A
        st.Page("views/ops.py", title="Журнал и качество", icon=":material/fact_check:"),            # часть A
    ],
}
st.sidebar.markdown(f"**AeroPulse** · аэропорт {config.AIRPORT_IATA}")
st.navigation(pages).run()
