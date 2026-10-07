# -*- coding: utf-8 -*-
"""測試用小頁面：6 格共用一個協調器，rerun 不應重抓。"""
import streamlit as st

from market_coordinator import MarketDataCoordinator, Source

CALLS = st.session_state.setdefault("_calls", [])


def _fetch(symbol, **params):
    CALLS.append((symbol, params.get("timeframe")))
    if symbol == "9996":
        raise RuntimeError("模擬這檔壞掉")
    return {"symbol": symbol, "lastPrice": 100}


@st.cache_resource
def coord():
    src = Source(_fetch, provider="Fugle", ttl_seconds=3600)
    return MarketDataCoordinator({"quote": src, "candles": src}, api_budget_per_minute={"Fugle": 50},
                                 error_backoff_seconds=3600)


cells = ["9991", "9992", "9993", "9991", "9996", "9994"]
views = ["quote", "candles", "quote", "candles", "quote", "candles"]   # 每格可選不同畫面
cols = st.columns(3)
for i, (s, v) in enumerate(zip(cells, views)):
    r = coord().get(v, s, timeframe="5" if v == "candles" else None)
    cols[i % 3].markdown(f"<span class='cell'>{s}/{v}:{r.status.name}</span>", unsafe_allow_html=True)
st.button("rerun")
