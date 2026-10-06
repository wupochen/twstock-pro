# -*- coding: utf-8 -*-
import glossary as g

TEXT_FIELDS = ("key", "term", "data_type", "plain_language", "how_to_read", "common_misunderstanding")


def test_unique_keys_and_count():
    keys = [t.key for t in g.all_terms()]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 50


def test_fields_complete():
    for t in g.all_terms():
        for f in TEXT_FIELDS:
            assert getattr(t, f).strip(), (t.key, f)
        assert t.data_type in g.DATA_TYPES, t.key
        assert t.applicable_horizons and all(h in g.ALL_HORIZONS for h in t.applicable_horizons), t.key
        assert all(x in g.NOT_APPLICABLE_VALUES for x in t.not_applicable_to), t.key
        assert t.system_role in g.SYSTEM_ROLES, t.key
        # 本站使用的週期必須是這個名詞會用到的週期
        assert set(t.used_by_engine_horizons) <= set(t.applicable_horizons), t.key


def test_plain_length():
    for t in g.all_terms():
        assert len(t.plain_language) <= g.PLAIN_MAX_CHARS, (t.key, len(t.plain_language))


def test_no_banned_words():
    for t in g.all_terms():
        text = "".join(getattr(t, f) for f in TEXT_FIELDS)
        for w in g.BANNED_WORDS:
            assert w not in text, (t.key, w)


def test_required_terms_present():
    must = {"kline", "red_k", "green_k", "ma", "bias", "support", "resistance", "rsi", "kd", "macd", "osc",
            "bollinger", "atr", "vwap", "at_bid", "at_ask", "ask_ratio", "orderbook", "best_bid_ask",
            "volume_ratio", "volume_spike", "limit_up", "limit_down", "locked_up", "locked_down",
            "institutional", "foreign", "trust", "dealer", "net_buy", "streak", "margin", "margin_change",
            "short", "order_size", "shareholding", "revenue", "yoy", "mom", "eps", "roe", "pe",
            "dividend_yield", "de_ratio", "fcf", "stop_loss", "take_profit", "r_multiple", "rr_ratio",
            "backtest", "win_rate", "expectancy", "sample_size", "direction", "risk_level",
            "actionability", "insufficient", "estimated", "realtime", "after_close", "third_party",
            "premium", "tracking_error"}
    assert must <= set(g.GLOSSARY)


def test_not_applicable_is_conceptual_only():
    """not_applicable_to 只能放商品類型，不能拿週期表示「本站沒用」。"""
    for t in g.all_terms():
        assert not set(t.not_applicable_to) & set(g.ALL_HORIZONS), t.key
    assert not g.is_applicable("eps", "ETF") and not g.is_applicable("roe", "ETF")
    assert not g.is_applicable("premium", "個股")
    assert g.is_applicable("eps", "個股") and g.is_applicable("rsi", "ETF")


def test_engine_usage_separate_from_applicability():
    assert set(g.ENGINE_USAGE) <= set(g.GLOSSARY)
    rsi = g.get("rsi")
    assert rsi.applicable_horizons == g.ALL_HORIZONS      # RSI 每個週期都能算
    assert rsi.system_role == "RISK"                        # 本站只拿來當風險標記
    assert not g.used_by_engine("rsi", "當沖")
    assert g.used_by_engine("kd", "短線") and not g.used_by_engine("kd", "長線")
    assert g.get("eps").used_by_engine_horizons == ("長線",)
    assert g.get("support").system_role == "INFO"


def test_tooltip_and_horizon():
    assert g.tooltip("rsi").startswith("RSI")
    assert any(t.key == "vwap" for t in g.by_horizon("當沖"))
    assert not any(t.key == "eps" for t in g.by_horizon("當沖"))
