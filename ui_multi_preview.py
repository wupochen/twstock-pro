# -*- coding: utf-8 -*-
"""多檔同時看盤預覽頁（第四段先行 P-E，只用虛構資料）。

每格內容（GPT 定版）：
  1 代號／名稱／現價／漲跌幅
  2 當日 mini chart＋VWAP
  3 方向／風險／能不能做（三個獨立狀態，不合成一顆總燈）
  4 當沖強度一行：同時段量比／外盤比／距 VWAP
  5 資料狀態點（綠＝即時、黃＝延遲、灰＝無資料）＋來源時間
  動作：放大／新分頁（同一份 watchlist 放在網址 ?w=，放大頁和多檔頁共用）

- 6 格是 compact mode：圖表較矮、原因只留一行、次要文字隱藏（ⓘ 仍有完整說明）。
- 手機窄螢幕時 Streamlit 會自動變成單欄。
- 不 import engine、不連任何 API。正式接資料時改由 MarketDataCoordinator 集中抓取，
  不讓每格自己呼叫 API。啟動：streamlit run ui_multi_preview.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import pricing
import ui_theme as ui
from ui_theme import C, tip

st.set_page_config(page_title="台股戰情室｜多檔看盤預覽", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(ui.css(), unsafe_allow_html=True)
st.markdown("""
<style>
.block-container { max-width: 100% !important; padding-left: 1.2rem; padding-right: 1.2rem; }
.cell .top { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.cell .nm { font-size:17px; font-weight:900; }
.cell .cd { color:#8b97a8; font-size:13px; margin-left:6px; }
.cell .px { font-size:26px; font-weight:900; font-variant-numeric: tabular-nums; text-align:right; }
.cell .chg { font-size:13px; font-weight:800; text-align:right; }
.compact .px { font-size:22px; } .compact .nm { font-size:15px; }
.lights { display:flex; gap:6px; margin:6px 0 2px; flex-wrap:wrap; }
.light { flex:1; min-width:78px; border-radius:9px; padding:3px 8px; background:#151c28; border-left:4px solid var(--c); }
.light .k { color:#8b97a8; font-size:11px; font-weight:700; }
.light .v { color:var(--c); font-size:14px; font-weight:900; }
.why1 { color:#c3ccd8; font-size:12.5px; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dt { display:flex; gap:12px; flex-wrap:wrap; font-size:12.5px; color:#c3ccd8; margin-top:4px;
      background:#151c28; border-radius:8px; padding:3px 8px; font-variant-numeric: tabular-nums; }
.dt b { font-weight:900; }
.foot { display:flex; justify-content:space-between; align-items:center; gap:6px; }
.fresh { font-size:12px; color:#c3ccd8; display:flex; align-items:center; gap:6px; }
.dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.zoom { color:#3ea6ff !important; font-size:13px; font-weight:800; text-decoration:none; border:1px solid #3ea6ff55;
        border-radius:8px; padding:2px 8px; white-space:nowrap; }
.zoom:hover { background:#3ea6ff22; }
.nodata { height:var(--h); display:flex; align-items:center; justify-content:center; color:#8b97a8;
          border:1px dashed #243042; border-radius:10px; margin:6px 0; font-size:14px; text-align:center; }
div[data-testid="stVerticalBlockBorderWrapper"] { background:#0f141d; border-color:#243042 !important; border-radius:14px !important; }
div[role="radiogroup"] label p { color:#e8edf5 !important; font-weight:700; }
</style>""", unsafe_allow_html=True)
st.markdown(ui.demo_banner(), unsafe_allow_html=True)

# ── 虛構資料 ─────────────────────────────────────────
# fresh: live=即時、stale=延遲、none=無資料
STOCKS = {
    "9991": dict(name="範例電子", ref=50.20, d="偏多", r="高", a="不宜追價", fresh="live", age=3,
                 why="均線多頭、外資連 3 買；RSI 82 過熱、今日已漲 4%", seed=1),
    "9992": dict(name="範例半導體", ref=612.0, d="中性偏多", r="中", a="可操作", fresh="live", age=2,
                 why="站上均價、同時段放量；法人中性", seed=2),
    "9993": dict(name="範例航運", ref=38.45, d="偏空", r="中", a="資料不足", fresh="stale", age=75,
                 why="跌破均價、內盤較多；報價超過 60 秒沒更新", seed=3),
    "9994": dict(name="範例生技", ref=88.6, d="資料不足", r="低", a="資料不足", fresh="none", age=None,
                 why="目前抓不到這檔的報價", seed=4),
    "9995": dict(name="範例金融", ref=27.15, d="中性", r="低", a="可操作", fresh="live", age=4,
                 why="價格在均價附近、量能正常", seed=5),
    "9996": dict(name="範例光電", ref=144.5, d="偏多", r="中", a="無法正常交易", fresh="live", age=1,
                 why="漲停鎖單，賣方幾乎沒有掛單", seed=6),
}
CODES = list(STOCKS)
DEFAULT_WATCH = CODES[:6]
T = "10:42:15"
FRESH = {"live": ("#3ee08f", "即時"), "stale": ("#f5b942", "延遲"), "none": ("#6b7686", "無資料")}


@st.cache_data
def intraday(code: str, n: int = 103):
    s = STOCKS[code]
    if s["fresh"] == "none":
        return None
    rng = np.random.default_rng(s["seed"])
    drift = {"偏多": 0.0006, "中性偏多": 0.0003, "偏空": -0.0005}.get(s["d"], 0.0)
    px = s["ref"] * np.exp(np.cumsum(rng.normal(drift, 0.0022, n)))
    if s["a"] == "無法正常交易":  # 示意鎖漲停：最後一段停在漲停
        up = float(pricing.limit_prices(s["ref"]).up)  # 漲停價依升降單位向下對齊
        px = np.minimum(px * 1.06, up)
        px[-25:] = up
    px = np.array([float(pricing.align_price(v, mode="nearest")) for v in px])  # 對齊合法升降單位
    vol = rng.integers(20, 400, n).astype(float)
    idx = pd.date_range("2026-10-06 09:00", periods=n, freq="1min")
    vwap = np.cumsum(px * vol) / np.cumsum(vol)
    ask_ratio = float(np.clip(0.5 + (px[-1] / s["ref"] - 1) * 4 + rng.normal(0, 0.03), 0.2, 0.9))
    stvr = float(np.round(rng.uniform(0.6, 2.4), 2))
    return dict(df=pd.DataFrame({"px": px, "vwap": vwap}, index=idx), ask_ratio=ask_ratio, stvr=stvr)


def mini_chart(df: pd.DataFrame, ref: float, height: int):
    last = df["px"].iloc[-1]
    col = ui.color_for_change(last - ref)
    fig = go.Figure()
    fig.add_hline(y=ref, line=dict(color="#56637a", width=1, dash="dot"))
    fig.add_trace(go.Scatter(x=df.index, y=df["px"], mode="lines", line=dict(color=col, width=1.8),
                             name="成交價", hovertemplate="%{x|%H:%M}　%{y:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=df.index, y=df["vwap"], mode="lines", line=dict(color="#e8edf5", width=1, dash="dot"),
                             name="均價", hoverinfo="skip"))
    fig.update_layout(template="plotly_dark", height=height, margin=dict(l=4, r=4, t=4, b=4), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False, tickformat="%H:%M", nticks=5, tickfont=dict(size=10, color=C["muted"]))
    fig.update_yaxes(gridcolor="#1c2533", tickfont=dict(size=10, color=C["muted"]), side="right")
    return fig


def light(k: str, v: str, color: str) -> str:
    return f"<div class='light' style='--c:{color}'><div class='k'>{k}</div><div class='v'>{ui.esc(v)}</div></div>"


def watch_qs(watch) -> str:
    return "w=" + ",".join(watch)


def cell(code: str, height: int, compact: bool, watch):
    with st.container(border=True):
        _cell(code, height, compact, watch)


def _cell(code: str, height: int, compact: bool, watch):
    s = STOCKS[code]
    data = intraday(code)
    head = f"<div><span class='nm'>{ui.esc(s['name'])}</span><span class='cd'>{code}</span></div>"
    if data is None:
        price_html = "<div><div class='px' style='color:#8b97a8'>—</div><div class='chg' style='color:#8b97a8'>無報價</div></div>"
    else:
        last = float(data["df"]["px"].iloc[-1])
        chg = last - s["ref"]
        col = ui.color_for_change(chg)
        arrow = "▲" if chg > 0 else "▼" if chg < 0 else "－"
        price_html = (f"<div><div class='px' style='color:{col}'>{last:,.2f}</div>"
                      f"<div class='chg' style='color:{col}'>{arrow} {abs(chg):.2f}（{chg / s['ref'] * 100:+.2f}%）</div></div>")
    st.markdown(
        f"<div class='cell{' compact' if compact else ''}'><div class='top'>{head}{price_html}</div>"
        f"<div class='lights'>{light('方向', s['d'], ui.DIRECTION_COLOR.get(s['d'], C['flat']))}"
        f"{light('風險', s['r'], ui.RISK_COLOR.get(s['r'], C['flat']))}"
        f"{light('能不能做', s['a'], ui.ACTION_COLOR.get(s['a'], C['flat']))}</div>"
        f"<div class='why1' title='{ui.esc(s['why'])}'>{ui.esc(s['why'])}</div></div>",
        unsafe_allow_html=True)

    if data is None:
        st.markdown(f"<div class='nodata' style='--h:{height}px'>暫時抓不到這檔的資料<br>其他格不受影響</div>",
                    unsafe_allow_html=True)
    else:
        df = data["df"]
        st.plotly_chart(mini_chart(df, s["ref"], height), use_container_width=True,
                        config={"displayModeBar": False}, key=f"chart_{code}")
        last, vw = float(df["px"].iloc[-1]), float(df["vwap"].iloc[-1])
        gap = (last / vw - 1) * 100
        gcol = ui.color_for_change(gap)
        acol = C["up"] if data["ask_ratio"] > 0.5 else C["down"]
        st.markdown(
            f"<div class='dt'><span>同時段量比{tip('same_time_volume_ratio')} <b>{data['stvr']:.2f} 倍</b></span>"
            f"<span>外盤比{tip('ask_ratio')} <b style='color:{acol}'>{data['ask_ratio'] * 100:.0f}%</b></span>"
            f"<span>距 VWAP{tip('vwap')} <b style='color:{gcol}'>{gap:+.2f}%</b></span></div>",
            unsafe_allow_html=True)

    dcol, dtxt = FRESH[s["fresh"]]
    when = "—" if s["age"] is None else (f"{T}（{s['age']} 秒前）" if not compact else f"{s['age']} 秒前")
    src = "" if compact else "富果・"
    st.markdown(
        f"<div class='foot'><span class='fresh'><span class='dot' style='background:{dcol}'></span>"
        f"{dtxt}・{src}{when}（示意）</span>"
        f"<a class='zoom' href='?focus={code}&{watch_qs(watch)}' target='_blank' "
        f"title='在新分頁打開，可拖到另一個螢幕'>⤢ 放大／新分頁</a></div>",
        unsafe_allow_html=True)


# ── watchlist：放在網址，放大頁與多檔頁共用 ───────────
def parse_watch(raw) -> list:
    if not raw:
        return list(DEFAULT_WATCH)
    seen = []
    for c in str(raw).split(","):
        if c in STOCKS and c not in seen:
            seen.append(c)
    return seen or list(DEFAULT_WATCH)


watch = parse_watch(st.query_params.get("w"))

# ── 放大模式（單檔） ─────────────────────────────────
focus = st.query_params.get("focus")
if focus is not None:
    if focus not in STOCKS or focus not in watch:
        st.warning("這個代號不在看盤清單裡，已回到多檔看盤。")
    else:
        s = STOCKS[focus]
        st.markdown(f"<a class='zoom' href='?{watch_qs(watch)}' target='_self'>← 回多檔看盤</a>",
                    unsafe_allow_html=True)
        data = intraday(focus)
        if data is None:
            st.markdown(ui.hero(s["name"], focus, 0, 0, 0, ui.badge("無資料", "demo")), unsafe_allow_html=True)
            st.info("暫時抓不到這檔的資料。")
        else:
            df = data["df"]
            last = float(df["px"].iloc[-1])
            chg = last - s["ref"]
            st.markdown(ui.hero(s["name"], focus, last, chg, chg / s["ref"] * 100,
                                ui.badge(f"即時・富果 {T}（示意）", "live") + ui.badge("示意資料", "demo")),
                        unsafe_allow_html=True)
            st.markdown(ui.status3(s["d"], ui.esc(s["why"]), s["r"], "（示意）", s["a"], "（示意）"),
                        unsafe_allow_html=True)
            st.plotly_chart(mini_chart(df, s["ref"], 420), use_container_width=True, config={"displayModeBar": False})
        st.caption("正式版的放大頁就是完整的單檔頁（K線、五檔、法人、風險參考價、資料狀況）。")
        st.stop()

# ── 多檔看盤 ─────────────────────────────────────────
c1, c2, c3 = st.columns([1.2, 3, 1.4])
with c1:
    layout = st.radio("版面", ["4 格（2×2）", "6 格（3×2）"], horizontal=True, label_visibility="collapsed")
n = 4 if layout.startswith("4") else 6
with c2:
    picks = st.multiselect("要看的股票（示意，只能選虛構代號）", CODES, default=watch[:6], max_selections=6,
                           format_func=lambda c: f"{c} {STOCKS[c]['name']}", label_visibility="collapsed")
with c3:
    st.selectbox("自動更新", ["每 5 秒", "每 10 秒", "每 30 秒", "暫停"], index=1, label_visibility="collapsed",
                 help="預覽頁不會真的更新；正式版由 MarketDataCoordinator 集中排程抓取")

# 清單順序保留使用者選的；4 格只顯示前 4 檔，切回 6 格不會打亂
watch = picks or list(DEFAULT_WATCH)
st.query_params["w"] = ",".join(watch)
shown = (watch + [c for c in CODES if c not in watch])[:n]
cols_per_row = 2 if n == 4 else 3
compact = n == 6
h = 220 if n == 4 else 150
for r in range(0, n, cols_per_row):
    row = st.columns(cols_per_row, gap="small")
    for col, code in zip(row, shown[r:r + cols_per_row]):
        with col:
            cell(code, h, compact, watch)

st.markdown("<div style='margin-top:12px;color:#8b97a8;font-size:12px'>"
            "資料狀態：🟢 即時　🟡 延遲（超過 60 秒沒更新）　⚪ 無資料。"
            "灰色虛線＝參考價（昨收）；白色虛線＝當日均價（VWAP）。"
            "方向／風險／能不能做由判斷引擎產生，這裡是示意。本站內容為資訊整理，不是投資建議。</div>",
            unsafe_allow_html=True)
