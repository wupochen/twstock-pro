# -*- coding: utf-8 -*-
"""介面主題（第四段先行，GPT 平行工作 P-B 核准）。

只負責「長相」：顏色、CSS、可重用的 HTML 小元件。
不 import engine、不做任何多空判斷；傳進來什麼就畫什麼。

設計原則：
- 深色底、台股慣例紅漲綠跌。
- 方向／風險／可操作三層一定分開顯示，不合成一個總分。
- 每個數字保留來源、時間、是否估算的標籤。
- 每個名詞旁有 ⓘ，滑過顯示 glossary 白話；新手模式直接把白話寫在下面。
"""
from __future__ import annotations

import html

import glossary

C = {
    "bg": "#07090f",
    "panel": "#0f141d",
    "panel2": "#151c28",
    "line": "#243042",
    "text": "#e8edf5",
    "muted": "#8b97a8",
    "up": "#ff4d4f",       # 漲：紅
    "down": "#1fc16b",     # 跌：綠
    "flat": "#c9d1dc",
    "gold": "#f5b942",
    "blue": "#3ea6ff",
    "purple": "#a78bfa",
}

DIRECTION_COLOR = {
    "偏多": C["up"], "中性偏多": "#ff8a80", "中性": C["flat"],
    "中性偏空": "#7ee0a8", "偏空": C["down"], "資料不足": C["muted"], "不適用": "#7f9cc0",
}
RISK_COLOR = {"低": C["down"], "中": C["gold"], "高": C["up"]}
ACTION_COLOR = {
    "可操作": C["down"], "等待回測": C["gold"], "不宜追價": C["gold"], "不宜新進場": C["gold"],
    "無法正常交易": C["up"], "不可當沖": C["up"], "市場已收盤": C["muted"], "資料不足": C["muted"],
}
BADGE_STYLE = {
    "live": ("#0b3d2a", "#3ee08f"),       # 即時
    "delayed": ("#3d2f0b", "#f5b942"),    # 延遲
    "after": ("#14284a", "#7fb6ff"),      # 盤後
    "est": ("#3a1630", "#f58ad0"),        # 估算
    "demo": ("#4a1010", "#ffb3b3"),       # 示意資料
}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def css() -> str:
    return f"""
<style>
.stApp {{ background: radial-gradient(1200px 500px at 10% -10%, rgba(62,166,255,.10), transparent 60%),
         radial-gradient(900px 400px at 100% 0%, rgba(255,77,79,.08), transparent 60%), {C['bg']}; color:{C['text']}; }}
.block-container {{ max-width: 1280px; padding-top: 1rem; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.demo-banner {{ position: sticky; top: 0; z-index: 99; background: repeating-linear-gradient(45deg,#4a1010,#4a1010 12px,#3a0c0c 12px,#3a0c0c 24px);
  color:#ffd6d6; font-weight:800; text-align:center; padding:8px 12px; border-radius:10px; letter-spacing:1px; margin-bottom:12px; border:1px solid #7a2020; }}
.hero {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap;
  background: linear-gradient(135deg,{C['panel']},{C['panel2']}); border:1px solid {C['line']}; border-radius:18px; padding:20px 24px; margin-bottom:14px; }}
.hero .name {{ font-size:28px; font-weight:900; }}
.hero .code {{ color:{C['muted']}; font-size:16px; margin-left:8px; font-weight:600; }}
.hero .meta {{ color:{C['muted']}; font-size:13px; margin-top:6px; }}
.hero .px {{ font-size:46px; font-weight:900; line-height:1; text-align:right; font-variant-numeric: tabular-nums; }}
.hero .chg {{ font-size:18px; font-weight:800; text-align:right; margin-top:6px; }}
.badge {{ display:inline-block; font-size:12px; font-weight:700; padding:2px 8px; border-radius:999px; margin:2px 4px 2px 0; white-space:nowrap; }}
.status3 {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px; margin: 6px 0 14px; }}
@media (max-width: 760px) {{ .status3 {{ grid-template-columns: 1fr; }} .hero .px {{ text-align:left; }} .hero .chg {{ text-align:left; }} }}
.slot {{ background:{C['panel']}; border:1px solid {C['line']}; border-radius:16px; padding:14px 16px; border-top:4px solid var(--c); }}
.slot .lbl {{ color:{C['muted']}; font-size:13px; font-weight:700; letter-spacing:.5px; }}
.slot .val {{ color:var(--c); font-size:26px; font-weight:900; margin:4px 0 6px; }}
.slot .why {{ color:#c3ccd8; font-size:13.5px; line-height:1.55; }}
.card {{ background:{C['panel']}; border:1px solid {C['line']}; border-radius:14px; padding:12px 14px; height:100%; }}
.card .t {{ color:{C['muted']}; font-size:13px; font-weight:700; }}
.card .v {{ font-size:22px; font-weight:900; margin-top:2px; font-variant-numeric: tabular-nums; }}
.card .s {{ color:{C['muted']}; font-size:12px; margin-top:4px; }}
.tip {{ position:relative; display:inline-flex; align-items:center; justify-content:center; width:16px; height:16px; margin-left:4px;
  border-radius:50%; background:{C['panel2']}; border:1px solid {C['line']}; color:{C['blue']}; font-size:11px; font-weight:900; cursor:help; vertical-align:middle; }}
.tip .pop {{ visibility:hidden; opacity:0; position:absolute; z-index:50; left:50%; bottom:130%; transform:translateX(-50%); width:240px;
  background:#0b0f16; color:{C['text']}; border:1px solid {C['blue']}; border-radius:10px; padding:10px 12px; font-size:12.5px; font-weight:500; line-height:1.55;
  box-shadow:0 8px 24px rgba(0,0,0,.5); transition:opacity .15s; text-align:left; }}
.tip:hover .pop, .tip:focus .pop {{ visibility:visible; opacity:1; }}
.newbie {{ color:#9fb3c8; font-size:12.5px; line-height:1.5; margin-top:4px; border-left:3px solid {C['blue']}; padding-left:8px; }}
.sec {{ font-size:18px; font-weight:900; margin:18px 0 8px; display:flex; align-items:center; gap:6px; }}
.ob {{ width:100%; border-collapse:collapse; font-variant-numeric: tabular-nums; font-size:15px; }}
.ob td {{ padding:5px 6px; border-bottom:1px solid {C['line']}; }}
.ob .bar {{ height:8px; border-radius:4px; }}
.reason li {{ margin:2px 0; }}
.foot {{ color:{C['muted']}; font-size:12px; margin-top:18px; line-height:1.6; }}
div[data-baseweb="tab-list"] button p {{ font-size:16px; font-weight:800; }}
</style>
"""


def demo_banner() -> str:
    return "<div class='demo-banner'>⚠️ 示意資料／非真實行情：此頁只用來看新介面長相，所有數字都是虛構的</div>"


def badge(text: str, kind: str = "live") -> str:
    bg, fg = BADGE_STYLE.get(kind, BADGE_STYLE["est"])
    return f"<span class='badge' style='background:{bg};color:{fg};border:1px solid {fg}55'>{esc(text)}</span>"


def tip(key: str) -> str:
    """名詞旁的 ⓘ，滑過或點一下顯示 glossary 白話。"""
    t = glossary.get(key)
    body = f"<b>{esc(t.term)}</b><br>{esc(t.plain_language)}<br><span style='color:{C['muted']}'>怎麼看：</span>{esc(t.how_to_read)}" \
           f"<br><span style='color:{C['gold']}'>常見誤解：</span>{esc(t.common_misunderstanding)}"
    return f"<span class='tip' tabindex='0'>i<span class='pop'>{body}</span></span>"


def term(label: str, key: str, newbie: bool = False) -> str:
    """名詞＋ⓘ；新手模式時下面再多一行白話。"""
    out = f"{esc(label)}{tip(key)}"
    if newbie:
        out += f"<div class='newbie'>{esc(glossary.get(key).plain_language)}</div>"
    return out


def color_for_change(chg: float) -> str:
    return C["up"] if chg > 0 else C["down"] if chg < 0 else C["flat"]


def hero(name: str, code: str, price: float, chg: float, chg_pct: float, meta_html: str) -> str:
    col = color_for_change(chg)
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "－"
    return f"""
<div class='hero'>
  <div><div class='name'>{esc(name)}<span class='code'>{esc(code)}</span></div><div class='meta'>{meta_html}</div></div>
  <div><div class='px' style='color:{col}'>{price:,.2f}</div>
  <div class='chg' style='color:{col}'>{arrow} {abs(chg):.2f}（{chg_pct:+.2f}%）</div></div>
</div>"""


def status_slot(layer: str, key: str, value: str, color: str, why_html: str, newbie: bool) -> str:
    return f"""
<div class='slot' style='--c:{color}'>
  <div class='lbl'>{term(layer, key)}</div>
  <div class='val'>{esc(value)}</div>
  <div class='why'>{why_html}</div>
  {f"<div class='newbie'>{esc(glossary.get(key).how_to_read)}</div>" if newbie else ""}
</div>"""


def status3(direction: str, d_why: str, risk: str, r_why: str, action: str, a_why: str, newbie: bool = False) -> str:
    """方向／風險／可操作三層，固定分開三格。"""
    return "<div class='status3'>" + \
        status_slot("① 方向", "direction", direction, DIRECTION_COLOR.get(direction, C["flat"]), d_why, newbie) + \
        status_slot("② 風險", "risk_level", risk, RISK_COLOR.get(risk, C["flat"]), r_why, newbie) + \
        status_slot("③ 現在能不能做", "actionability", action, ACTION_COLOR.get(action, C["flat"]), a_why, newbie) + \
        "</div>"


def card(title_html: str, value: str, sub_html: str = "", color: str = None) -> str:
    return f"<div class='card'><div class='t'>{title_html}</div>" \
           f"<div class='v' style='color:{color or C['text']}'>{esc(value)}</div><div class='s'>{sub_html}</div></div>"


def section(title: str, key: str = None) -> str:
    return f"<div class='sec'>{esc(title)}{tip(key) if key else ''}</div>"
