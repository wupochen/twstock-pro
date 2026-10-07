# -*- coding: utf-8 -*-
"""新單檔頁（真資料）AppTest：回放 RAW_CAPTURE，不連網。"""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parents[1] / "ui_live.py")


def _md(at):
    return "\n".join(m.value for m in at.markdown)


def test_replay_owner_page_renders_engine_disabled(monkeypatch):
    monkeypatch.setenv("LIVE_REPLAY", "1")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    md = _md(at)
    assert md.count("判斷引擎尚未啟用") == 3 and "資料不足" not in md.split("資料狀況清單")[0].split("status3")[1][:2000]
    for s in ("台積電", "外盤", "可歸類成交", "VWAP", "五檔掛單", "三大法人", "日 K 線", "月營收", "資料狀況清單", "暫定"):
        assert s in md, s


def test_external_viewer_sees_no_quote(monkeypatch):
    monkeypatch.delenv("LIVE_REPLAY", raising=False)
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.secrets["OWNER_EMAILS"] = ["owner@example.com"]
    at.secrets["FUGLE_TOKEN"] = ""          # 沒金鑰：就算授權判斷出錯也不會打出去
    at.secrets["FINMIND_TOKEN"] = ""
    at.run()
    assert not at.exception
    md = _md(at)
    assert "只開放給擁有者使用" in "\n".join(i.value for i in at.info)
    assert "class='hero'" not in md and "五檔掛單" not in md
    assert "尚未開放的功能" not in md
