# -*- coding: utf-8 -*-
"""新單檔頁（真資料版）。尚未接進 everlight_app.py，單獨啟動：streamlit run ui_live.py

- 資料全部經 live_data（協調器快取＋限流；每個區塊各自授權守門）。
- 只有 secrets 的 OWNER_EMAILS 內的登入者看得到富果等未授權資料；其他人只看到「為什麼看不到」。
- 判斷引擎（Gate 2.4）尚未啟用：三格固定顯示「判斷引擎尚未啟用」，不顯示任何方向結論。
- 回放模式（本機測試用）：環境變數 LIVE_REPLAY=1 → 用 tests/fixtures/raw 的 RAW_CAPTURE，頁頂標示「回放」。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import indicators as ind
import live_data as ld
import ui_theme as ui
from capabilities import ProviderConfig, fast_streaming, intraday_ranking, multi_user_display
from data_bundle import DAILY, FUNDAMENTALS, INSTITUTIONAL, ORDER_BOOK, QUOTE, REVENUE, TPE
from data_license import BlockAudit, ViewerScope
from ui_theme import C, badge, card, section, term

REPLAY = os.environ.get("LIVE_REPLAY") == "1"
RAW_DIR = Path(__file__).resolve().parent / "tests" / "fixtures" / "raw"
REPLAY_NOW = datetime(2026, 10, 7, 11, 21, 0, tzinfo=TPE)

st.set_page_config(page_title="台股戰情室｜單檔（真資料）", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(ui.css(), unsafe_allow_html=True)


# ── 金鑰與觀看者 ─────────────────────────────────────
def _secret(k: str, default=""):
    try:
        return st.secrets[k]
    except Exception:  # noqa: BLE001 — 沒有 secrets 檔就當沒設定
        return default


def _login_email():
    try:
        return getattr(st.user, "email", None)
    except Exception:  # noqa: BLE001
        return None


def _owner_list():
    v = _secret("OWNER_EMAILS", [])
    return [v] if isinstance(v, str) else list(v)


# ── 協調器（所有人共用一個；金鑰用函式讀，不存在物件裡）──
def _replay_fetchers():
    def load(n):
        return json.loads((RAW_DIR / n).read_text(encoding="utf-8"))

    idx = pd.bdate_range(end="2026-10-06", periods=160)
    base = pd.Series(range(160), index=idx, dtype=float)
    df = pd.DataFrame({"Open": 2300 + base * 1.6, "High": 2310 + base * 1.6, "Low": 2290 + base * 1.6,
                       "Close": 2302 + base * 1.6, "Volume": 30_000_000.0})

    def candles(symbol, timeframe=None, **_):
        return load("fugle_candles_2330_1m_20261007_112005.json" if timeframe == "1"
                    else "fugle_candles_2330_5m_20261007_112011.json")
    return {ld.K_QUOTE: lambda s, **_: load("fugle_quote_2330_20261007_0932.json"), ld.K_CANDLES: candles,
            ld.K_INST: lambda s, **_: load("finmind_institutional_1416.json"),
            ld.K_REVENUE: lambda s, **_: load("finmind_revenue_1711.json"),
            ld.K_DAILY: lambda s, **_: df, ld.K_INFO: lambda s, **_: {"trailingEps": 52.1, "trailingPE": 24.6}}


@st.cache_resource
def coordinator():
    if REPLAY:
        return ld.make_coordinator(_replay_fetchers(), now=lambda: REPLAY_NOW)
    return ld.make_coordinator(ld.make_fetchers(lambda: _secret("FUGLE_TOKEN"), lambda: _secret("FINMIND_TOKEN")))


@st.cache_resource
def block_audit():
    return BlockAudit()


def _now():
    return REPLAY_NOW if REPLAY else datetime.now(timezone.utc)


# ── 小工具 ───────────────────────────────────────────
def t_str(dt, fmt="%H:%M:%S"):
    return "—" if dt is None else dt.astimezone(TPE).strftime(fmt)


def fmt(v, nd=2, unit=""):
    return "—" if v is None else f"{v:,.{nd}f}{unit}"


def src_badge(sec, label=None):
    kind = {"Fugle": "live", "FinMind": "after", "yfinance": "delayed"}.get(sec.source_name, "est")
    stale = "・過期" if sec.freshness.name == "STALE" else ""
    return badge(f"{label or sec.source_name}・資料時間 {t_str(sec.as_of, '%m/%d %H:%M:%S')}{stale}", kind)


def plot_layout(fig, h):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=C["panel"], height=h,
                      margin=dict(l=8, r=8, t=8, b=8), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04, x=0, font=dict(color=C["text"])),
                      font=dict(size=12, color=C["text"]))
    fig.update_xaxes(gridcolor=C["line"])
    fig.update_yaxes(gridcolor=C["line"])
    return fig


# ── 頁首 ─────────────────────────────────────────────
viewer = ViewerScope.OWNER if REPLAY else ld.viewer_scope(_login_email(), _owner_list())
if REPLAY:
    st.markdown("<div class='demo-banner'>⏪ 回放模式：使用 2026-10-07 盤中實際抓到的資料（RAW_CAPTURE），不是現在的行情</div>",
                unsafe_allow_html=True)

top_l, top_m, top_r = st.columns([3, 1, 1])
with top_l:
    symbol = st.text_input("🔍 股票代號", value="2330", max_chars=6).strip().upper()
with top_m:
    newbie = st.toggle("🔰 新手模式", value=True)
with top_r:
    auto = st.toggle("每 15 秒自動更新", value=False, disabled=REPLAY,
                     help="免費方案每分鐘最多 60 次；本頁每次更新最多用 3 次富果")

if not symbol.isalnum():
    st.error("代號只能是英數字")
    st.stop()


@st.fragment(run_every=15 if auto and not REPLAY else None)
def body(symbol: str):
    if viewer == ViewerScope.EXTERNAL:
        # 非擁有者：完全不抓行情（省額度，也不會有未授權資料進到這次畫面）
        st.info("這個網站目前只開放給擁有者使用。行情資料的對外顯示授權還在申請中，"
                "所以這裡看不到股價、五檔、K 線等內容。")
        return
    coord = coordinator()
    first = ld.fetch_all(coord, symbol)
    suffix = ld.yf_suffix_for(first[ld.K_QUOTE].value if first[ld.K_QUOTE].ok else None)
    res = first if suffix == ".TW" else ld.fetch_all(coord, symbol, yf_suffix=suffix)
    v = ld.build_view_model(symbol, res, _now(), viewer, block_audit())

    # ── 報價 ──
    q = v.get(QUOTE)
    if q is not None:
        last, ref = v.value(QUOTE, "last_price"), v.value(QUOTE, "reference_price")
        chg = v.value(QUOTE, "change") or 0.0
        pct = v.value(QUOTE, "change_percent") or 0.0
        meta = (src_badge(q, "富果") + f"<br>{term('參考價', 'ref_price')} {fmt(ref)}　｜　開 {fmt(v.value(QUOTE, 'open'))}"
                f"　高 {fmt(v.value(QUOTE, 'high'))}　低 {fmt(v.value(QUOTE, 'low'))}")
        if v.value(QUOTE, "is_limit_up_price"):
            meta += "　" + badge("漲停", "est")
        if v.value(QUOTE, "is_limit_down_price"):
            meta += "　" + badge("跌停", "est")
        st.markdown(ui.hero(v.name or symbol, symbol, last if last is not None else 0.0, chg, pct, meta),
                    unsafe_allow_html=True)
        if last is None:
            st.warning("今天還沒有成交價")

    # ── 三格：判斷引擎尚未啟用 ──
    st.markdown(section("方向／風險／現在能不能做", "direction"), unsafe_allow_html=True)
    why = ui.esc(v.engine_why)
    st.markdown("<div class='status3'>" + "".join(
        ui.status_slot(lbl, key, v.engine_state, C["muted"], why, newbie)
        for lbl, key in (("① 方向", "direction"), ("② 風險", "risk_level"), ("③ 現在能不能做", "actionability")))
        + "</div>", unsafe_allow_html=True)

    # ── 盤中關鍵數字 ──
    if q is not None:
        st.markdown(section("盤中關鍵數字"), unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        f = v.flow
        ratio_txt, share_txt = f.display_pair() if f else ("外盤比：—", "可歸類成交：—")
        ratio_col = None if not f or f.ask_ratio is None else (C["up"] if f.ask_ratio > 0.5 else C["down"])
        flow_sub = ui.esc(share_txt) + ("" if not f or not f.note else f"<br>⚠️ {ui.esc(f.note)}")
        if f and f.quality.name == "LOW_COVERAGE":
            flow_sub += f"<br>⚠️ {ui.esc(f.quality.value)}，比例參考性較低"
        c1.markdown(card(term("內外盤比", "ask_ratio", newbie), ratio_txt.replace("外盤比：", "外盤 "), flow_sub, ratio_col),
                    unsafe_allow_html=True)
        vw = v.value(QUOTE, "vwap")
        chk = {True: "與富果均價一致", False: "⚠️ 與富果均價不一致", None: "無法核對"}[v.vwap_check]
        c2.markdown(card(term("VWAP 當日均價", "vwap", newbie), fmt(vw), chk), unsafe_allow_html=True)
        c3.markdown(card(term("成交量", "volume", newbie), fmt(v.value(QUOTE, "trade_volume"), 0, " 張"),
                         f"成交值 {fmt((v.value(QUOTE, 'trade_value') or 0) / 1e8, 2)} 億"), unsafe_allow_html=True)
        c4.markdown(card("成交筆數", fmt(v.value(QUOTE, "transactions"), 0, " 筆"), src_badge(q, "富果")),
                    unsafe_allow_html=True)

    # ── 盤中 K 線（1／5 分）──
    ks = [n for n in ("1分K", "5分K") if v.get(n) is not None]
    if ks:
        st.markdown(section("盤中 K 線", "kline"), unsafe_allow_html=True)
        tf = st.radio("週期", ks, horizontal=True, label_visibility="collapsed", key=f"tf_{symbol}")
        sec = v.get(tf)
        df = pd.DataFrame(sec.rows)
        if len(df):
            df["t"] = df["start"].map(lambda d: d.astimezone(TPE).replace(tzinfo=None))
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
            for state, op, nm in (("SETTLED", 1.0, "K線（已穩定）"), ("PROVISIONAL", 0.45, "K線（暫定，可能被修正）")):
                d = df[df.state == state]
                if len(d):
                    fig.add_trace(go.Candlestick(x=d.t, open=d.open, high=d.high, low=d.low, close=d.close, name=nm,
                                                 opacity=op,
                                                 increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
                                                 decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"])),
                                  row=1, col=1)
            fig.add_trace(go.Scatter(x=df.t, y=df.day_average, name="當日均價", line=dict(color=C["gold"], width=1.3)),
                          row=1, col=1)
            fig.add_trace(go.Bar(x=df.t, y=df.volume, name="量（張）",
                                 marker_color=[C["up"] if c >= o else C["down"] for c, o in zip(df.close, df.open)],
                                 marker_opacity=[1.0 if s == "SETTLED" else 0.45 for s in df.state]), row=2, col=1)
            st.plotly_chart(plot_layout(fig, 420), width="stretch", config={"displayModeBar": False})
            n_prov = int((df.state == "PROVISIONAL").sum())
            st.markdown(src_badge(sec, "富果") + badge(f"淡色 {n_prov} 根為暫定（結束未滿 {int(sec.meta['settle_seconds'])} 秒）", "est"),
                        unsafe_allow_html=True)
            if newbie:
                st.markdown("<div class='newbie'>最後幾根顏色較淡的 K 棒還「沒定案」：資料源在 K 棒結束後十幾秒內可能還會修正。"
                            "之後的判斷規則只會用已穩定的 K 棒。</div>", unsafe_allow_html=True)

    # ── 五檔＋法人 ──
    c_ob, c_inst = st.columns(2)
    ob = v.get(ORDER_BOOK)
    with c_ob:
        if ob is not None:
            st.markdown(section("五檔掛單", "orderbook"), unsafe_allow_html=True)
            bids = v.value(ORDER_BOOK, "bids") or []
            asks = v.value(ORDER_BOOK, "asks") or []
            n = max(len(bids), len(asks), 1)
            mx = max([l["size"] or 0 for l in bids + asks] + [1])
            rows = ""
            for i in range(n):
                b = bids[i] if i < len(bids) else None
                a = asks[i] if i < len(asks) else None
                bw = (b["size"] or 0) / mx * 100 if b else 0
                aw = (a["size"] or 0) / mx * 100 if a else 0
                rows += (f"<tr><td style='width:28%'><div class='bar' style='background:{C['up']};width:{bw:.0f}%;margin-left:auto'></div></td>"
                         f"<td style='text-align:right;color:{C['muted']}'>{fmt(b['size'], 0) if b else ''}</td>"
                         f"<td style='text-align:right;color:{C['up']};font-weight:800'>{fmt(b['price']) if b else '—'}</td>"
                         f"<td style='color:{C['down']};font-weight:800'>{fmt(a['price']) if a else '—'}</td>"
                         f"<td style='color:{C['muted']}'>{fmt(a['size'], 0) if a else ''}</td>"
                         f"<td style='width:28%'><div class='bar' style='background:{C['down']};width:{aw:.0f}%'></div></td></tr>")
            st.markdown(f"<table class='ob'><tr style='color:{C['muted']};font-size:12px'><td></td><td style='text-align:right'>張</td>"
                        f"<td style='text-align:right'>買價</td><td>賣價</td><td>張</td><td></td></tr>{rows}</table>"
                        + src_badge(ob, "富果") + (badge(ob.note, "est") if ob.note else ""), unsafe_allow_html=True)
    with c_inst:
        inst = v.get(INSTITUTIONAL)
        if inst is not None and inst.rows:
            st.markdown(section("三大法人（近 10 日，張）", "institutional"), unsafe_allow_html=True)
            rows = inst.rows[-10:]
            f2 = go.Figure()
            for k, colr in (("外資", C["blue"]), ("投信", C["gold"]), ("自營商", C["purple"])):
                f2.add_trace(go.Bar(x=[r["date"][5:] for r in rows], y=[r[k] for r in rows], name=k, marker_color=colr))
            f2.update_layout(barmode="group")
            st.plotly_chart(plot_layout(f2, 280), width="stretch", config={"displayModeBar": False})
            st.markdown(badge(f"盤後・FinMind・{inst.note}", "after") + badge("單位：張", "after"), unsafe_allow_html=True)

    # ── 日K（指標用 indicators.py，與舊頁同一套公式）──
    dk = v.get(DAILY)
    if dk is not None and dk.rows:
        st.markdown(section("日 K 線（已收完）", "kline"), unsafe_allow_html=True)
        d = pd.DataFrame(dk.rows).rename(columns=str.capitalize).set_index("Date")
        d.index = pd.to_datetime(d.index)
        d = ind.compute_kline_indicators(d).tail(120)
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name="日K",
                                     increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
                                     decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"])), row=1, col=1)
        for col, colr in (("MA5", C["gold"]), ("MA20", C["blue"])):
            fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, line=dict(color=colr, width=1.3)), row=1, col=1)
        fig.add_trace(go.Bar(x=d.index, y=d.Volume / 1000, name="量（張）",
                             marker_color=[C["up"] if c >= o else C["down"] for c, o in zip(d.Close, d.Open)]), row=2, col=1)
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(plot_layout(fig, 440), width="stretch", config={"displayModeBar": False})
        last = d.iloc[-1]
        st.markdown(badge(f"日K・yfinance・第三方延遲資料・最後一根 {d.index[-1]:%m/%d}", "delayed")
                    + badge(f"RSI {fmt(last.RSI, 1)}　K {fmt(last.K, 1)}　D {fmt(last.D, 1)}", "after"),
                    unsafe_allow_html=True)

    # ── 月營收＋基本面 ──
    c_rev, c_fund = st.columns(2)
    with c_rev:
        rev = v.get(REVENUE)
        if rev is not None and rev.rows:
            st.markdown(section("月營收（億元）", "revenue"), unsafe_allow_html=True)
            rows = rev.rows[-13:]
            f3 = go.Figure(go.Bar(x=[r["period"] for r in rows], y=[(r["revenue"] or 0) / 1e8 for r in rows],
                                  marker_color=C["blue"], name="營收"))
            st.plotly_chart(plot_layout(f3, 260), width="stretch", config={"displayModeBar": False})
            st.markdown(badge(f"FinMind・{rev.note}", "after"), unsafe_allow_html=True)
    with c_fund:
        fu = v.get(FUNDAMENTALS)
        if fu is not None:
            st.markdown(section("基本面", "eps"), unsafe_allow_html=True)
            pct = lambda x: None if x is None else x * 100  # noqa: E731
            items = [("EPS（近四季）", fmt(v.value(FUNDAMENTALS, "eps"), 2, " 元")),
                     ("本益比", fmt(v.value(FUNDAMENTALS, "pe"), 1, " 倍")),
                     ("股價淨值比", fmt(v.value(FUNDAMENTALS, "pb"), 2, " 倍")),
                     ("ROE", fmt(pct(v.value(FUNDAMENTALS, "roe")), 1, "%")),
                     ("殖利率（近 12 月）", fmt(pct(v.value(FUNDAMENTALS, "dividend_yield_ttm")), 2, "%"))]
            st.markdown("<table class='ob' style='font-size:14.5px'>" + "".join(
                f"<tr><td>{a}</td><td style='font-weight:800'>{b}</td></tr>" for a, b in items) + "</table>"
                + badge("yfinance・第三方", "delayed") + (badge(fu.note, "est") if fu.note else ""), unsafe_allow_html=True)

    # ── 看不到的區塊（未授權）──
    if v.blocked:
        st.markdown(section("目前看不到的資料"), unsafe_allow_html=True)
        st.markdown("<ul class='reason'>" + "".join(f"<li>🔒 {ui.esc(n)}：{ui.esc(why)}</li>" for n, _, why in v.blocked)
                    + "</ul>", unsafe_allow_html=True)

    # ── 資料狀況清單 ──
    st.markdown(section("資料狀況清單", "third_party"), unsafe_allow_html=True)
    trs = "".join(f"<tr><td>{ui.esc(l.section)}</td><td>{ui.esc(l.source)}</td><td>{t_str(l.as_of, '%m/%d %H:%M:%S')}</td>"
                  f"<td>{ui.esc(l.availability)}</td><td>{ui.esc(l.freshness)}</td><td>{ui.esc(l.fetch_status)}</td>"
                  f"<td style='color:{C['muted']}'>{ui.esc(l.note)}</td></tr>" for l in v.status)
    st.markdown(f"<table class='ob' style='font-size:13.5px'><tr style='color:{C['muted']}'><td>資料</td><td>來源</td>"
                f"<td>資料時間</td><td>完整度</td><td>新鮮度</td><td>這次</td><td>說明</td></tr>{trs}</table>",
                unsafe_allow_html=True)

    # ── 先做好、尚未開放的功能（只給擁有者看狀態）──
    if viewer == ViewerScope.OWNER:
        with st.expander("尚未開放的功能（等方案／授權）"):
            cfg = ProviderConfig()
            for cap in (intraday_ranking(cfg, viewer), fast_streaming(cfg, ["rt", "ob", "k1", "k5", "k15", "rt"], viewer),
                        multi_user_display(ld.rendered_sources(v))):
                st.markdown(f"- **{cap.feature.value}**：{'可用' if cap.enabled else '關閉'}　{ui.esc(cap.reason)}")
            st.caption("富果呼叫：" + "；".join(coord.stats.summary()))

    st.markdown(f"<div class='foot'>更新時間 {t_str(_now())}。本頁為資訊整理，不是投資建議；"
                "方向判斷規則尚未啟用。</div>", unsafe_allow_html=True)


body(symbol)
