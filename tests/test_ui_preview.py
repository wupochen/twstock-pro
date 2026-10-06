# -*- coding: utf-8 -*-
"""P-B 介面預覽：GPT 的四條限制寫成測試。"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ui_theme as ui

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "ui_preview.py").read_text(encoding="utf-8")


def _html(at):
    return "\n".join(m.value for m in at.markdown)


def test_preview_runs_without_error():
    at = AppTest.from_file(str(ROOT / "ui_preview.py"), default_timeout=60).run()
    assert not at.exception
    html = _html(at)
    # 1. 頂部永久示意標示
    assert "示意資料／非真實行情" in html
    # 3. 三層分開，且沒有總分
    for layer in ("① 方向", "② 風險", "③ 現在能不能做"):
        assert layer in html
    assert "AI" not in html and "總分" not in html
    # 4. 保留來源／時間／估算
    for word in ("即時・富果", "盤後・FinMind", "資料狀況清單", "估算"):
        assert word in html


def test_preview_uses_fictional_symbol_only():
    # 2. 不用真實個股數字
    assert '"9999"' in SRC and "範例科技" in SRC
    for real in ("1711", "永光", "2330", "1416"):
        assert real not in SRC


def test_preview_isolated_from_engine_and_app():
    imports = [l for l in SRC.splitlines() if l.startswith(("import ", "from "))]
    for l in imports:
        for mod in ("engine", "everlight_app", "requests", "fugle", "yfinance", "FinMind"):
            assert mod not in l, l


def test_newbie_mode_toggle():
    at = AppTest.from_file(str(ROOT / "ui_preview.py"), default_timeout=60).run()
    on = _html(at).count("class='newbie'")
    at.toggle[0].set_value(False).run()
    off = _html(at).count("class='newbie'")
    assert on > 10 and off == 0


def test_status3_and_tip():
    h = ui.status3("偏多", "x", "高", "y", "無法正常交易", "z")
    assert h.count("class='slot'") == 3
    assert ui.DIRECTION_COLOR["偏多"] == ui.C["up"] and ui.DIRECTION_COLOR["偏空"] == ui.C["down"]
    t = ui.tip("rsi")
    assert "RSI" in t and "常見誤解" in t
    assert "&lt;script&gt;" in ui.card("t", "<script>")  # 數值已跳脫 → 不會被注入
