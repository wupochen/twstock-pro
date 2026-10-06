# -*- coding: utf-8 -*-
"""多檔看盤預覽（P-E）：GPT 規格寫成測試。"""
import re
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

import pricing

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "ui_multi_preview.py")
SRC = (ROOT / "ui_multi_preview.py").read_text(encoding="utf-8")
ZOOM = "⤢ 放大／新分頁"


def _html(at):
    return "\n".join(m.value for m in at.markdown)


def _run(**qp):
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in qp.items():
        at.query_params[k] = v
    return at.run()


def test_four_and_six_grid_three_layers_and_strength_row():
    at = _run()
    assert not at.exception
    assert "示意資料／非真實行情" in _html(at)
    assert _html(at).count(ZOOM) == 4
    at.radio[0].set_value("6 格（3×2）").run()
    assert not at.exception
    h = _html(at)
    assert h.count(ZOOM) == 6
    for k in ("方向", "風險", "能不能做"):              # 三層獨立，不合成一顆總燈
        assert h.count(f"<div class='k'>{k}</div>") == 6
    assert h.count("class='dt'") == 5                    # 當沖強度一行（無資料那格沒有）
    assert "class='cell compact'" in h                   # 6 格是 compact mode


def test_one_cell_missing_others_render():
    at = _run()
    at.radio[0].set_value("6 格（3×2）").run()
    h = _html(at)
    assert not at.exception
    assert h.count("暫時抓不到這檔的資料") == 1
    assert len(re.findall(r"class='px' style='color:#(?!8b97a8)", h)) == 5


def test_freshness_dots():
    at = _run()
    at.radio[0].set_value("6 格（3×2）").run()
    h = _html(at)
    for word in ("即時・", "延遲・", "無資料・"):
        assert word in h


def test_switch_4_6_keeps_watchlist_order():
    at = _run(w="9995,9993,9991,9996,9992,9994")
    assert at.multiselect[0].value == ["9995", "9993", "9991", "9996", "9992", "9994"]
    first4 = re.findall(r"<span class='cd'>(\d+)</span>", _html(at))
    assert first4 == ["9995", "9993", "9991", "9996"]
    at.radio[0].set_value("6 格（3×2）").run()
    assert re.findall(r"<span class='cd'>(\d+)</span>", _html(at)) == ["9995", "9993", "9991", "9996", "9992", "9994"]
    at.radio[0].set_value("4 格（2×2）").run()
    assert re.findall(r"<span class='cd'>(\d+)</span>", _html(at)) == first4
    assert "w=9995,9993,9991,9996,9992,9994" in _html(at)  # 放大連結帶著同一份清單


def test_focus_page_and_safe_fallback():
    at = _run(focus="9991", w="9991,9992")
    assert not at.exception
    h = _html(at)
    assert "回多檔看盤" in h and "① 方向" in h and ZOOM not in h and "w=9991,9992" in h
    bad = _run(focus="<script>", w="9991")
    assert not bad.exception and bad.warning and ZOOM in _html(bad)
    notin = _run(focus="9995", w="9991,9992")
    assert notin.warning and ZOOM in _html(notin)


def test_watchlist_param_is_sanitized():
    at = _run(w="9991,abc,9991,<x>")
    assert at.multiselect[0].value == ["9991"]


def test_fictional_and_isolated():
    for real in ("1711", "永光", "2330", "1416"):
        assert real not in SRC
    for l in [l for l in SRC.splitlines() if l.startswith(("import ", "from "))]:
        for mod in ("engine", "everlight_app", "requests", "fugle", "yfinance", "FinMind"):
            assert mod not in l, l


def test_demo_prices_are_legal_ticks():
    """畫面上每格的現價都必須是合法升降單位。"""
    at = _run()
    at.radio[0].set_value("6 格（3×2）").run()
    prices = re.findall(r"class='px' style='color:[^']+'>([\d,\.]+)<", _html(at))
    assert len(prices) == 5
    for v in prices:
        assert pricing.is_valid_price(Decimal(v.replace(",", ""))), v
