# -*- coding: utf-8 -*-
"""先做好、預設關閉的功能：功能開關、排行、推送核心、富果推送、區塊守門。全部不連網。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import capabilities as cap
import data_bundle as db
from data_license import BlockAudit, ViewerScope, filter_displayable_sections
from fugle_stream import FugleStreamTransport
from ranking import RankKind, RankScope, fugle_snapshot_ranking, watchlist_ranking
from streaming import ConnectionState, StreamConfig, StreamSession, SubscriptionLimitExceeded, SubscriptionSpec

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "tests" / "fixtures" / "doc_based"
OWNER, EXT = ViewerScope.OWNER, ViewerScope.EXTERNAL


def doc(name):
    return json.loads((DOC / name).read_text(encoding="utf-8"))


# ── 功能開關 ──
def test_today_everything_off_with_plain_reasons():
    c = cap.ProviderConfig()
    r = cap.intraday_ranking(c, OWNER)
    assert (r.available, r.allowed, r.enabled) == (False, False, False)
    assert r.reason == "目前行情方案未開放排行榜資料"
    s = cap.fast_streaming(c, ["rt"] * 6, OWNER)
    assert not s.available and "推送額度 5" in s.reason and "需要 6" in s.reason
    m = cap.multi_user_display(["Fugle"])
    assert not m.allowed and "Fugle" in m.reason


def test_three_layers_are_not_mixed():
    dev = cap.ProviderConfig(fugle_plan="developer")
    r_owner, r_ext = cap.intraday_ranking(dev, OWNER), cap.intraday_ranking(dev, EXT)
    assert r_owner.enabled and r_owner.detail["provider"] == "Fugle"
    assert r_ext.available and not r_ext.allowed and "授權" in r_ext.reason     # 方案夠，但授權不允許
    s = cap.fast_streaming(dev, ["rt"] * 6, OWNER)
    assert s.available and s.allowed and not s.enabled and "未連線" in s.reason  # 服務離線
    s2 = cap.fast_streaming(cap.ProviderConfig(fugle_plan="developer", stream_online=True), ["rt"] * 6, OWNER)
    assert s2.enabled


def test_subscriptions_counted_by_channel_not_cells():
    assert cap.required_subscriptions(["rt", "ob", "k5", "ta"]) == 3
    c = cap.ProviderConfig()            # 免費 5 個
    assert cap.fast_streaming(c, ["rt", "ob", "k1", "ta"], OWNER).available is True
    assert cap.fast_streaming(c, ["rt", "ob", "k1", "rt", "ob", "k5"], OWNER).available is False


def test_multi_user_uses_rendered_sources_only():
    assert cap.multi_user_display([]).allowed
    assert not cap.multi_user_display(["TWSE"]).allowed       # 官方資料也要逐一確認，目前未確認


# ── 排行 ──
def test_fugle_movers_and_actives_doc_based():
    up = fugle_snapshot_ranking(doc("fugle_snapshot_movers_doc.json"), RankKind.CHANGE_PERCENT_UP, "TSE")
    assert up.fixture_origin == "DOC_BASED" and up.scope == RankScope.MARKET_INTRADAY
    r = up.rows[0]
    assert (r.rank, r.symbol, r.change_percent, r.volume_lots) == (1, "2901", 10, 640)
    assert r.as_of.isoformat().startswith("2023-05-29T05:30:00") and r.distribution_status == "LICENSE_UNCONFIRMED"
    vol = fugle_snapshot_ranking(doc("fugle_snapshot_actives_doc.json"), RankKind.VALUE, "TSE")
    assert vol.rows[0].value_twd == 31019803000
    with pytest.raises(ValueError):
        fugle_snapshot_ranking(doc("fugle_snapshot_actives_doc.json"), RankKind.VALUE, "OTC")


def test_watchlist_ranking_is_labelled_not_market():
    q = {"2330": {"change_percent": -0.2, "name": "台積電"}, "1711": {"change_percent": 1.5}, "9999": {}}
    w = watchlist_ranking(q, RankKind.CHANGE_PERCENT_UP, "Fugle")
    assert w.scope == RankScope.WATCHLIST and "非市場排行" in w.scope.value
    assert [x.symbol for x in w.rows] == ["1711", "2330"]


# ── 推送核心＋富果 ──
class FakeSock:
    def __init__(self):
        self.out, self.closed = [], False

    def send(self, m):
        self.out.append(m)

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def _session(limit=5):
    sock, clk, got = FakeSock(), Clock(), []
    tr = FugleStreamTransport(lambda: "KEY-NOT-LOGGED", lambda: sock)
    s = StreamSession(tr, StreamConfig(limit), got.append, clk)
    return s, tr, sock, clk, got


def test_auth_subscribe_resubscribe_after_reconnect():
    s, tr, sock, clk, got = _session()
    s.subscribe(SubscriptionSpec("trades", "2330"))
    s.connect()
    assert [m["event"] for m in sock.out] == ["auth"]          # 還沒登入不送訂閱
    s.handle(doc("fugle_ws_authenticated_doc.json"))
    assert s.state == ConnectionState.AUTHENTICATED and sock.out[-1]["event"] == "subscribe"
    s.handle(doc("fugle_ws_subscribed_doc.json"))
    assert ("trades", "2330") in s.confirmed
    s.reconnect()
    assert s.reconnects == 1 and not s.confirmed
    s.handle(doc("fugle_ws_authenticated_doc.json"))
    assert [m["event"] for m in sock.out].count("subscribe") == 2   # 重連後自動重新訂閱
    assert all(m.get("data", {}).get("apikey") != "KEY-NOT-LOGGED" for m in tr.sent)   # 紀錄裡沒有金鑰


def test_data_dedupe_and_heartbeat_stale():
    s, tr, sock, clk, got = _session()
    s.connect(); s.handle(doc("fugle_ws_authenticated_doc.json"))
    ev = doc("fugle_ws_trades_doc.json")
    s.handle(ev); s.handle(ev)
    assert len(got) == 1 and s.duplicates == 1
    e = got[0]
    assert (e.channel, e.symbol, e.event_id) == ("trades", "2330", "6652422") and e.data["price"] == 568
    clk.t += timedelta(seconds=91)
    assert s.check_heartbeat() == ConnectionState.STALE
    s.handle({"event": "heartbeat", "data": {"time": "1"}})
    assert s.state == ConnectionState.AUTHENTICATED


def test_subscription_limit_and_unknown_channel():
    s, tr, sock, clk, got = _session(limit=2)
    s.subscribe(SubscriptionSpec("trades", "2330")); s.subscribe(SubscriptionSpec("books", "2330"))
    with pytest.raises(SubscriptionLimitExceeded):
        s.subscribe(SubscriptionSpec("trades", "1711"))
    s.subscribe(SubscriptionSpec("trades", "2330"))            # 重複訂閱不算數
    assert s.subscription_count == 2
    with pytest.raises(ValueError):
        tr.subscribe_message(SubscriptionSpec("ranking", "2330"))


def test_transport_refuses_to_open_when_disabled():
    tr = FugleStreamTransport(lambda: "x")
    with pytest.raises(RuntimeError):
        tr.open()


# ── 區塊守門 ──
def test_section_level_guard_with_audit():
    t = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)
    secs = [db.Section("即時報價", "Fugle", db.SourceType.VENDOR, t),
            db.Section("月營收", "FinMind", db.SourceType.THIRD_PARTY, t)]
    shown, blocked = filter_displayable_sections(secs, OWNER)
    assert len(shown) == 2 and not blocked
    audit = BlockAudit(now=lambda: t)
    shown, blocked = filter_displayable_sections(secs, EXT, "單檔頁", audit)
    assert not shown and len(blocked) == 2 and "尚未取得對外顯示授權" in blocked[0][1]
    rec = audit.records[0]
    assert (rec.section, rec.blocked_source, rec.distribution_status, rec.viewer_scope, rec.feature) == \
        ("即時報價", "Fugle", "LICENSE_UNCONFIRMED", "EXTERNAL", "單檔頁")


def test_doc_based_fixtures_are_not_golden():
    origins = json.loads((DOC / "ORIGINS.json").read_text(encoding="utf-8"))
    for p in DOC.glob("*.json"):
        if p.name != "ORIGINS.json":
            assert origins[p.name]["origin"] == "DOC_BASED", p.name


def test_new_modules_isolated():
    for name in ("capabilities.py", "ranking.py", "streaming.py", "fugle_stream.py", "data_license.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
        for mod in ("streamlit", "everlight_app", "requests", "websocket", "yfinance"):
            assert not any(mod in l for l in imports), (name, mod)
