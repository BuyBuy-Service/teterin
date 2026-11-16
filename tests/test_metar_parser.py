"""Часть B: разбор METAR. Сводки — реальные форматы ORD (часть взята из загруженных данных)."""
import pytest

from metar_parser import flight_category, parse, weather_tokens

CASES = [
    # текст, ожидания
    ("KORD 140251Z 33013G20KT 10SM FEW050 02/M04 A3010 RMK AO2 SLP200",
     dict(wind_kt=13, gust_kt=20, vis_sm=10, ceiling_ft=None, temp_c=2, flight_cat="VFR", precip=0)),
    ("KORD 161451Z 27015G25KT 3SM -SN BR OVC008 M02/M04 A2990 RMK AO2",
     dict(gust_kt=25, vis_sm=3, ceiling_ft=800, snow=1, mist=1, rain=0, flight_cat="IFR", temp_c=-2)),
    ("KORD 051751Z 22012KT 2SM +TSRA BR BKN015CB OVC030 24/22 A2985 RMK AO2 TSB32",
     dict(ts=1, rain=1, snow=0, ceiling_ft=1500, vis_sm=2, flight_cat="IFR")),
    ("KORD 120351Z 00000KT 1/4SM FG VV002 08/08 A3021 RMK AO2",
     dict(wind_kt=0, vis_sm=0.25, ceiling_ft=200, fog=1, flight_cat="LIFR")),
    ("KORD 230951Z 04009KT 4SM -FZRA BR OVC006 M01/M02 A3001 RMK AO2",
     dict(fzra=1, rain=1, precip=1, ceiling_ft=600, flight_cat="IFR")),
    ("KORD 101551Z 30018G31KT 10SM BKN045 OVC250 05/M06 A2975",
     dict(gust_kt=31, ceiling_ft=4500, flight_cat="VFR")),
    ("KORD 101651Z 31011KT 5SM HZ SCT030 BKN028 31/18 A2999",
     dict(vis_sm=5, ceiling_ft=2800, flight_cat="MVFR", precip=0)),
    ("KORD 021151Z VRB04KT 10SM -RA OVC012 12/10 A2990 RMK AO2",
     dict(wind_kt=4, rain=1, ceiling_ft=1200, flight_cat="MVFR")),
    ("KORD 151851Z 25010KT 10SM VCTS SCT050CB 28/20 A2992",
     dict(ts=0, flight_cat="VFR")),  # гроза в окрестности (VC) — не на аэродроме
    ("KORD 080451Z 36022G35KT 1/2SM +SN BLSN VV005 M08/M10 A3002 RMK AO2",
     dict(snow=1, gust_kt=35, vis_sm=0.5, flight_cat="LIFR")),
    ("KORD 190651Z 18006KT 7SM -SHRA FEW020 BKN040 18/16 A2995",
     dict(rain=1, precip=1, ceiling_ft=4000, flight_cat="VFR")),
    ("KORD 251351Z 26008KT 1 1/2SM BR OVC004 03/02 A3010",
     dict(vis_sm=1.5, ceiling_ft=400, mist=1, precip=0, flight_cat="LIFR")),
    ("KORD 040051Z 29014KT 10SM SKC M15/M22 A3045",
     dict(temp_c=-15, ceiling_ft=None, flight_cat="VFR")),
    ("KORD 071251Z 21007KT 3SM -DZ BR OVC009 09/08 A2988",
     dict(rain=1, ceiling_ft=900, flight_cat="IFR")),
    ("KORD 291951Z 23016G24KT 10SM -TSRAGR BKN035CB 26/19 A2980",
     dict(ts=1, rain=1, precip=1, gust_kt=24)),
]


@pytest.mark.parametrize("raw,exp", CASES)
def test_parse(raw, exp):
    p = parse(raw, 2026, 1)
    assert p["parse_ok"] == 1
    for k, v in exp.items():
        assert p[k] == pytest.approx(v) if isinstance(v, float) else p[k] == v, k


def test_weather_tokens_ignore_remarks_and_groups():
    assert weather_tokens("KORD 140251Z AUTO 33013KT 10SM CLR 02/M04 A3010 RMK AO2 RAB15E30") == []
    assert weather_tokens("KORD 161451Z 27015KT 3SM -SN BR OVC008 M02/M04 A2990") == ["-SN", "BR"]


def test_garbage_does_not_crash():
    p = parse("KORD 1@#$ ??? ", 2026, 1)
    assert p["parse_ok"] == 0


@pytest.mark.parametrize("vis,ceil,cat", [(10, None, "VFR"), (5, None, "MVFR"), (10, 3000, "MVFR"),
                                          (2.5, 5000, "IFR"), (10, 900, "IFR"), (0.75, None, "LIFR"),
                                          (10, 400, "LIFR"), (None, None, None)])
def test_flight_category(vis, ceil, cat):
    assert flight_category(vis, ceil) == cat
