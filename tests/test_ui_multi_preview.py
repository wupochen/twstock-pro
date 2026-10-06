# -*- coding: utf-8 -*-
"""多檔看盤預覽（P-E／P-F）：GPT 規格寫成測試。"""
import re
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

import pricing

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "ui_multi_preview.py")
SRC = (ROOT / "ui_multi_preview.py").read_text(encoding="utf-8")
ZOOM = "⤢ 放大／新分頁"
ALL6 = "9991,9992,9993,9994,9995,9996"


def _html(at):
    return "\n".join(m.value for m in at.markdown)


def _run(**qp):
    at = AppTest.from_file(APP, default_timeout=90)
    for k, v in qp.items():
        at.query_params[k] = v
    return at.run()


def _six(at):
    next(r for r in at.radio if "6 格（3×2）" in r.options).set_value("6 格（3×2）").run()
    return at


def _toggle(at, label, value):
    next(t for t in at.toggle if label in t.label).set_value(value).run()
    return at


def _codes(at):
    return re.findall(r"<span class='cd'>(\d+)</span>", _html(at))


def test_four_and_six_grid_three_layers_and_strength_row():
    at = _run(w=ALL6)
    assert not at.exception
    assert "示意資料／非真實行情" in _html(at)
    assert _html(at).count(ZOOM) == 4
    _six(at)
    assert not at.exception
    h = _html(at)
    assert h.count(ZOOM) == 6
    for k in ("方向", "風險", "能不能做"):
        assert h.count(f"<div class='k'>{k}</div>") == 6
    assert h.count("class='dt'") == 5          # 當沖強度一行（無資料那格沒有）
    assert "class='cell compact'" in h


def test_one_cell_missing_others_render():
    at = _six(_run(w=ALL6))
    h = _html(at)
    assert not at.exception
    assert h.count("暫時抓不到這檔的資料") == 1


def test_freshness_dots_and_newbie_hints():
    at = _six(_run(w=ALL6))
    h = _html(at)
    for word in ("即時・", "延遲・", "無資料・"):
        assert word in h
    assert h.count("class='hint'") == 3        # 鎖漲停、延遲、無資料各一個
    _toggle(at, "新手提示", False)
    assert "class='hint'" not in _html(at)


def test_switch_4_6_keeps_watchlist_order():
    at = _run(w="9995,9993,9991,9996,9992,9994")
    assert _codes(at) == ["9995", "9993", "9991", "9996"]
    assert at.query_params["w"] == "9995,9993,9991,9996,9992,9994"   # 4 格時第 5、6 格仍保留在網址
    _six(at)
    assert _codes(at) == ["9995", "9993", "9991", "9996", "9992", "9994"]


def test_each_cell_view_and_switch_all():
    at = _six(_run(w=ALL6, v="rt,ta,k5,chip,ob,rt"))
    assert not at.exception
    h = _html(at)
    assert "日K・只用已收完的K線" in h and "盤後・資料日 10/05" in h and "class='ob'" in h
    sel = next(s for s in at.selectbox if s.label == "🔀 全部切換")
    sel.set_value("技術分析").run()
    assert not at.exception
    assert _html(at).count("日K・只用已收完的K線") == 6
    assert at.query_params["v"] == "ta,ta,ta,ta,ta,ta"


def test_switch_all_only_affects_stock_cells():
    at = _six(_run(w="9991,9992,RANK,9993,9996,INDEX"))
    next(s for s in at.selectbox if s.label == "🔀 全部切換").set_value("技術分析").run()
    assert not at.exception
    h = _html(at)
    assert h.count("日K・只用已收完的K線") == 4
    assert "示意排行榜" in h and "加權指數" in h


def test_one_cell_minute_k_does_not_change_others():
    at = _six(_run(w=ALL6, v="rt,rt,rt,rt,rt,rt"))
    sel = next(s for s in at.selectbox if s.label == "第 2 格畫面")
    sel.set_value("k5").run()
    assert not at.exception
    assert at.query_params["v"] == "rt,k5,rt,rt,rt,rt"


def test_invalid_panel_mode_falls_back():
    at = _run(w=ALL6, v="rt,<b>,xx,ta")
    assert not at.exception
    assert at.query_params["v"].split(",")[:4] == ["rt", "ta", "rt", "rt"]


def test_watchlists_switch_whole_group():
    at = _run()
    sel = next(s for s in at.selectbox if s.label == "📋 自選清單")
    sel.set_value("長期觀察").run()
    assert _codes(at) == ["9992", "9995", "9997", "9994"]
    assert "波段觀察" in sel.options


def test_rank_and_index_cells_and_toggles():
    at = _six(_run(w="9991,9992,RANK,9993,9996,INDEX"))
    assert not at.exception
    h = _html(at)
    assert "排行只呈現數字高低，不代表推薦" in h and "加權指數" in h and "櫃買指數" in h
    _toggle(at, "允許排行榜格", False)
    assert "排行只呈現數字高低" not in _html(at)


def test_rank_button_puts_stock_into_target_cell():
    at = _six(_run(w="9991,9992,RANK,9993,9996,9995"))
    btn = next(b for b in at.button if b.label.startswith("1. "))
    assert btn.disabled                                # 沒選格子前不能換
    next(s for s in at.selectbox if s.label == "放到第幾格").set_value(1).run()
    btn = next(b for b in at.button if b.label.startswith("1. "))
    assert not btn.disabled
    code = btn.label.split()[1]
    btn.click().run()
    assert not at.exception
    w = at.query_params["w"].split(",")
    assert w[0] == code and len(set(w)) == len(w)     # 放到第 1 格，且同一檔不重複


def test_alerts_trigger_and_can_be_turned_off():
    at = _run(w=ALL6)
    h = _html(at)
    assert "class='alertbar'" in h and "條件成立｜9991 範例電子：站上當日均價" in h
    assert "class='alerting'" in h
    bar = h.split("class='alertbar'>")[1].split("</div>")[0]
    for w in ("買進", "放空", "賣出", "訊號"):
        assert w not in bar
    _toggle(at, "條件提醒", False)
    assert "class='alertbar'" not in _html(at)


def test_stale_data_does_not_trigger_price_alert():
    at = _run(w=ALL6)
    h = _html(at)
    assert "9993 範例航運：跌破當日均價" not in h.split("class='alertbar'")[1].split("</div>")[0]
    side = "\n".join(m.value for m in at.sidebar.markdown)
    assert "資料延遲，暫停判斷" in side and "條件成立" in side and "等待中" in side


def test_blink_off_keeps_static_highlight():
    at = _run(w=ALL6)
    _toggle(at, "提醒閃爍效果", False)
    h = _html(at)
    assert "class='alerting'" not in h and "class='alerting-static'" in h


def test_time_compare_never_fakes_a_trade():
    at = _six(_run(w=ALL6, v="rt,rt,k5,rt,rt,ta"))
    _toggle(at, "時間對照", True)
    assert not at.exception
    h = _html(at)
    assert h.count("🕒 10:00") == 4                 # 5 格即時／分K，其中無資料一格不顯示；日K 那格不跟
    seen_no_trade = False
    for m in range(0, 103):
        next(x for x in at.slider).set_value(m).run()
        h = _html(at)
        if "該分鐘無成交" in h:
            seen_no_trade = True
            assert "最後一筆成交" in h
            break
    assert seen_no_trade


def test_layout_and_watchlist_saved_separately():
    at = _run(w=ALL6, v="ta,chip,rt,rt,rt,rt")
    next(t for t in at.text_input if t.label == "版面名稱").set_value("早盤").run()
    next(b for b in at.button if b.label == "儲存目前版面").click().run()
    assert not at.exception
    assert "早盤" in next(s for s in at.selectbox if s.label == "🗂️ 我的版面").options
    # 換自選清單：股票換了，但版面（每格畫面）不被覆蓋
    next(s for s in at.selectbox if s.label == "📋 自選清單").set_value("長期觀察").run()
    assert _codes(at) == ["9992", "9995", "9997", "9994"]
    assert at.query_params["v"].startswith("ta,chip")
    assert at.session_state.layouts["早盤"][:2] == ("ta", "chip")


def test_reset_cells():
    at = _run(w=ALL6, v="ta,chip,ob,k5,rt,rt")
    next(b for b in at.button if "重設所有格子" in b.label).click().run()
    assert not at.exception
    assert at.query_params["v"] == "rt,rt,rt,rt,rt,rt"


def test_focus_page_and_safe_fallback():
    at = _run(focus="9991", w="9991,9992")
    assert not at.exception
    h = _html(at)
    assert "回多檔看盤" in h and "① 方向" in h and ZOOM not in h
    bad = _run(focus="<script>", w="9991")
    assert not bad.exception and bad.warning
    notin = _run(focus="9995", w="9991,9992")
    assert notin.warning


def test_watchlist_param_is_sanitized():
    at = _run(w="9991,abc,9991,<x>")
    assert _codes(at)[0] == "9991" and "abc" not in at.query_params["w"]


def test_fictional_and_isolated():
    for real in ("1711", "永光", "2330", "1416"):
        assert real not in SRC
    for l in [l for l in SRC.splitlines() if l.strip().startswith(("import ", "from "))]:
        for mod in ("engine", "everlight_app", "requests", "fugle", "yfinance", "FinMind"):
            assert mod not in l, l
    for w in ("建議買進", "建議賣出", "推薦買", "必漲"):
        assert w not in SRC


def test_demo_prices_are_legal_ticks():
    at = _six(_run(w=ALL6))
    prices = re.findall(r"class='px' style='color:[^']+'>([\d,\.]+)<", _html(at))
    assert len(prices) == 5
    for v in prices:
        assert pricing.is_valid_price(Decimal(v.replace(",", ""))), v
