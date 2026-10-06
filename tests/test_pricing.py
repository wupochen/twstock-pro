from decimal import Decimal as D
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pricing as P


def test_asset_type():
    assert P.asset_type_of("1711") == P.STOCK
    assert P.asset_type_of("2330") == P.STOCK
    assert P.asset_type_of("0050") == P.ETF
    assert P.asset_type_of("00878") == P.ETF
    assert P.asset_type_of("00679B") == P.ETF
    assert P.asset_type_of("ABC") == P.UNKNOWN


def test_stock_ticks():
    assert P.tick_size(9.99) == D("0.01")
    assert P.tick_size(10) == D("0.05")
    assert P.tick_size(49.95) == D("0.05")
    assert P.tick_size(50) == D("0.1")
    assert P.tick_size(100) == D("0.5")
    assert P.tick_size(500) == D("1")
    assert P.tick_size(1000) == D("5")


def test_etf_ticks():
    assert P.tick_size(49.99, P.ETF) == D("0.01")
    assert P.tick_size(50, P.ETF) == D("0.05")
    assert P.tick_size(180, P.ETF) == D("0.05")


def test_twse_official_example():
    # 證交所範例：基準價 40.60 → 漲停 44.65、跌停 36.55
    lp = P.limit_prices(40.60)
    assert lp.up == D("44.65") and lp.down == D("36.55")


def test_1711_limit():
    lp = P.limit_prices(44.20)
    assert lp.up == D("48.6") and lp.down == D("39.8")


def test_cross_boundary_alignment_basic():
    assert P.align_price(49.97, mode="up") == D("50")        # 跨到 50 元級距
    assert P.align_price(53.93, mode="up") == D("54")        # 目標價依自己級距 0.1
    assert P.align_price(53.93, mode="down") == D("53.9")
    assert P.align_price(100.2, mode="down") == D("100")
    assert P.align_price(99.96, mode="up") == D("100")
    assert P.align_price(9.999, mode="up") == D("10")
    assert P.align_price(1003, mode="down") == D("1000")
    assert P.align_price(997.5, mode="up") == D("998")


def test_limit_crossing_boundary():
    # 基準 46.0 → 50.6 跨到 0.1 級距：漲停 50.6
    lp = P.limit_prices(46.0)
    assert lp.up == D("50.6")
    for v in (lp.up, lp.down):
        assert P.is_valid_price(v)


def test_provided_and_special():
    lp = P.limit_prices(40, provided_up=44, provided_down=36)
    assert lp.source == "資料源提供"
    assert P.limit_prices(40, special_day=True).up is None
    assert P.limit_prices(40, asset_type=P.UNKNOWN).source == "無法判斷"


def test_risk_levels_valid_and_aligned():
    n = 40
    closes = [40 + i * 0.2 for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    cur = closes[-1]
    lim = P.limit_prices(closes[-2])
    rr = P.risk_reference_levels(cur, highs, lows, closes, "短線", limit=lim)
    assert rr.ok, rr.problems
    assert rr.stop < D(str(cur)) < rr.tp1 < rr.tp2
    for v in (rr.stop, rr.tp1, rr.tp2):
        assert P.is_valid_price(v)
    assert "未經歷史回測" in rr.label


def test_risk_levels_insufficient_history():
    rr = P.risk_reference_levels(50, [1] * 5, [1] * 5, [1] * 5, "短線")
    assert not rr.ok


def test_validator():
    assert P.validate_long_levels(48.6, 46.9, 50.19, 48.6)  # 舊版 1711 錯誤情境必須被擋
    assert P.validate_long_levels(48.6, 46.9, 50.3, 52.0) == []


def test_risk_amount():
    # 進場 48.6、停損 46.9、1 張：價差 1,700 + 手續費 69 + 66 + 稅 140
    assert P.risk_amount(48.6, 46.9, 1) == 1700 + 69 + 66 + 140


# ---- GPT 要求補的 5 類邊界／異常測試 ----

def test_exact_boundaries():
    for price, tick in [(10, "0.05"), (50, "0.1"), (100, "0.5"), (500, "1"), (1000, "5")]:
        assert P.tick_size(price) == D(tick)          # 正好在邊界 → 用上一級（較大）的 tick
        assert P.is_valid_price(price)                 # 邊界價本身合法
    assert P.tick_size("9.99") == D("0.01")


def test_cross_down_from_above():
    assert P.align_price(50.02, mode="down") == D("50")       # 股票：50.0 是 ≤50.02 的最大合法價
    assert P.align_price(10.03, mode="down") == D("10")
    assert P.align_price(100.3, mode="down") == D("100")
    assert P.align_price(500.7, mode="down") == D("500")
    assert P.align_price(50.02, P.ETF, "down") == D("50")
    # 往下跨級距後，低於邊界的價格必須用小 tick
    assert P.align_price(49.99, mode="down") == D("49.95")
    assert P.align_price(49.99, P.ETF, "down") == D("49.99")


def test_etf_boundaries():
    assert P.align_price(49.999, P.ETF, "up") == D("50")
    assert P.align_price(50.01, P.ETF, "up") == D("50.05")
    assert P.align_price(50.01, P.ETF, "down") == D("50")
    assert P.is_valid_price(49.99, P.ETF)
    assert not P.is_valid_price(50.01, P.ETF)


def test_source_limit_not_overridden():
    lp = P.limit_prices(44.20, provided_up=48.60, provided_down=39.80)
    assert lp.source == "資料源提供"
    assert (lp.up, lp.down) == (D("48.6"), D("39.8"))
    # 就算資料源給的值跟一般規則不同，也不得被重算覆蓋
    lp2 = P.limit_prices(44.20, provided_up=99, provided_down=1)
    assert (lp2.up, lp2.down) == (D("99"), D("1"))
    assert lp2.is_suspect and "異常" in lp2.note       # 不覆蓋，但要標記可疑
    assert not lp.is_suspect                           # 正常值不標記
    lp3 = P.limit_prices(44.20, provided_up=30, provided_down=40)
    assert lp3.is_suspect                              # 順序顛倒
    lp4 = P.limit_prices(None, provided_up=48.6, provided_down=39.8)
    assert lp4.source == "資料源提供" and not lp4.is_suspect   # 沒參考價時無從比對，不標記


def test_invalid_inputs_are_safe():
    nan = float("nan")
    for bad in (0, -5, nan, None, "abc", float("inf")):
        assert P.tick_size(bad) is None
        assert P.align_price(bad) is None
        assert not P.is_valid_price(bad)
    assert P.tick_size(50, P.UNKNOWN) is None
    assert P.limit_prices(nan).source == "無法判斷"
    assert P.limit_prices(0).up is None
    flat = [10.0] * 30                       # 完全沒有波動 → ATR = 0 → 不得硬算
    assert P.atr(flat, flat, flat) is None
    rr = P.risk_reference_levels(10.0, flat, flat, flat, "短線")
    assert not rr.ok and rr.stop is None
    assert P.risk_reference_levels(nan, flat, flat, flat).stop is None
    assert P.risk_amount(nan, 10, 1) is None
    assert P.validate_long_levels(nan, 1, 2, 3)


def test_asset_info_priority():
    assert P.asset_info("0050").source == "已知清單"
    assert P.asset_info("00679B").subtype == P.ETF_BOND
    assert P.asset_info("00999").source == "代號推測"
    assert P.asset_info("12345").asset_type == P.UNKNOWN
    meta = {"type": P.STOCK}
    assert P.asset_info("0050", metadata=meta).asset_type == P.STOCK   # 商品清單優先
