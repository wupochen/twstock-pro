# -*- coding: utf-8 -*-
"""富果 WebSocket 的 StreamTransport（DOC_BASED：依官方文件寫成，尚未實際連線驗證）。

端點：wss://api.fugle.tw/marketdata/v1.0/stock/streaming
登入：{"event":"auth","data":{"apikey":...}}
訂閱：{"event":"subscribe","data":{"channel":..., "symbol":...}}
事件：authenticated／subscribed／heartbeat（約 30 秒）／data（含 id＝頻道 ID、channel）
取消訂閱的訊息格式文件未寫，unsubscribe_message 先用 {"event":"unsubscribe","data":{"id":頻道 ID}}，
實際連線時必須以 RAW_CAPTURE 驗證後才能啟用。
金鑰只從外部傳入（Streamlit secrets），不寫在程式裡、不寫進紀錄。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

from data_bundle import from_epoch_us
from streaming import StreamEvent, SubscriptionSpec

ENDPOINT = "wss://api.fugle.tw/marketdata/v1.0/stock/streaming"
CHANNELS = ("trades", "candles", "books", "aggregates", "indices")


class FugleStreamTransport:
    provider = "Fugle"

    def __init__(self, api_key_getter: Callable[[], str], socket_factory: Optional[Callable[[], Any]] = None):
        self._key = api_key_getter                 # 用函式取得，避免把金鑰存在物件屬性裡
        self._factory = socket_factory
        self._sock = None
        self.sent: list = []                       # 測試用：記錄送出的訊息種類（不含金鑰）
        self.channel_ids: Dict[Tuple[str, str], str] = {}

    def open(self) -> None:
        if self._factory is None:
            raise RuntimeError("推送功能尚未啟用（capabilities.FAST_STREAMING 關閉）")
        self._sock = self._factory()

    def close(self) -> None:
        if self._sock is not None and hasattr(self._sock, "close"):
            self._sock.close()
        self._sock = None

    def send(self, message: Dict[str, Any]) -> None:
        safe = dict(message)
        if safe.get("event") == "auth":
            safe = {"event": "auth", "data": {"apikey": "***"}}
        self.sent.append(safe)
        if self._sock is not None and hasattr(self._sock, "send"):
            self._sock.send(message)

    def auth_message(self) -> Dict[str, Any]:
        return {"event": "auth", "data": {"apikey": self._key()}}

    def subscribe_message(self, spec: SubscriptionSpec) -> Dict[str, Any]:
        if spec.channel not in CHANNELS:
            raise ValueError(f"富果沒有「{spec.channel}」頻道")
        return {"event": "subscribe", "data": {"channel": spec.channel, "symbol": spec.symbol}}

    def unsubscribe_message(self, spec: SubscriptionSpec) -> Dict[str, Any]:
        return {"event": "unsubscribe", "data": {"id": self.channel_ids.get(spec.key())}}

    def parse(self, raw: Dict[str, Any], received_at: datetime):
        ev = raw.get("event")
        data = raw.get("data") or {}
        if ev == "authenticated":
            return "authenticated", None
        if ev == "subscribed":
            key = (data.get("channel"), data.get("symbol"))
            if data.get("id"):
                self.channel_ids[key] = data["id"]
            return "subscribed", StreamEvent(self.provider, key[0], key[1], {}, None, received_at, data.get("id"))
        if ev == "heartbeat":
            return "heartbeat", None
        if ev == "data":
            ch = raw.get("channel")
            sym = data.get("symbol")
            t = from_epoch_us(data.get("time") or data.get("lastUpdated"))
            serial = data.get("serial")
            return "data", StreamEvent(self.provider, ch, sym, data, t, received_at,
                                       None if serial is None else str(serial))
        if ev == "error":
            return "error", None
        return "other", None
