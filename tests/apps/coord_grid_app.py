# -*- coding: utf-8 -*-
"""測試用小頁面：6 格共用一個協調器，rerun 不應重抓。"""
import streamlit as st

from market_coordinator import MarketDataCoordinator

CALLS = st.session_state.setdefault("_calls", [])


def _fetch(symbol):
    CALLS.append(symbol)
    if symbol == "9996":
        raise RuntimeError("模擬這檔壞掉")
    return {"symbol": symbol, "lastPrice": 100}


@st.cache_resource
def coord():
    return MarketDataCoordinator({"quote": _fetch}, ttl={"quote": 3600}, error_backoff=3600)


cells = st.session_state.get("cells", ["9991", "9992", "9993", "9991", "9996", "9994"])
cols = st.columns(3)
res = coord().get_many("quote", cells)
for i, s in enumerate(cells):
    r = res[s]
    cols[i % 3].markdown(f"<span class='cell'>{s}:{r.status.name}</span>", unsafe_allow_html=True)
st.button("rerun")
