# -*- coding: utf-8 -*-
"""推送通道核心（與資料提供者無關）。先做好、不實際連線（見 capabilities.FAST_STREAMING）。

提供者（富果、Shioaji…）各自實作 StreamTransport（怎麼連、怎麼送訊息、怎麼把原始訊息轉成 StreamEvent），
這裡負責共通的：連線狀態、訂閱額度、斷線重連後重新訂閱、心跳逾時、重複事件過濾、最後訊息時間。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple


class ConnectionState(str, Enum):
    DISCONNECTED = "未連線"
    CONNECTING = "連線中"
    AUTHENTICATED = "已登入"
    STALE = "心跳逾時"
    CLOSED = "已關閉"


@dataclass(frozen=True)
class SubscriptionSpec:
    channel: str          # trades／books／candles／aggregates／indices（依提供者）
    symbol: str

    def key(self) -> Tuple[str, str]:
        return (self.channel, self.symbol)


@dataclass(frozen=True)
class StreamEvent:
    provider: str
    channel: str
    symbol: str
    data: Dict[str, Any]
    event_time: Optional[datetime]       # 資料本身的時間（由提供者解析）
    received_at: datetime
    event_id: Optional[str] = None       # 提供者有序號就放序號；沒有就用 (channel, symbol, event_time, 內容) 去重

    def dedupe_key(self) -> Tuple:
        if self.event_id is not None:
            return (self.channel, self.symbol, "id", self.event_id)
        return (self.channel, self.symbol, self.event_time, repr(sorted(self.data.items())))


class StreamTransport(Protocol):
    """提供者實作：只負責收發與格式轉換。"""
    provider: str

    def open(self) -> None: ...
    def close(self) -> None: ...
    def send(self, message: Dict[str, Any]) -> None: ...
    def auth_message(self) -> Dict[str, Any]: ...
    def subscribe_message(self, spec: SubscriptionSpec) -> Dict[str, Any]: ...
    def unsubscribe_message(self, spec: SubscriptionSpec) -> Dict[str, Any]: ...
    def parse(self, raw: Dict[str, Any], received_at: datetime) -> Tuple[str, Optional[StreamEvent]]:
        """回傳 (種類, 事件)：種類為 authenticated／subscribed／heartbeat／data／error／other。"""
        ...


class SubscriptionLimitExceeded(Exception):
    pass


@dataclass
class StreamConfig:
    subscription_limit: int
    heartbeat_timeout_seconds: float = 90.0     # 文件說 30 秒一次心跳；逾時門檻是設定值，連線後實測再調
    dedupe_window: int = 5000


class StreamSession:
    def __init__(self, transport: StreamTransport, config: StreamConfig,
                 on_event: Callable[[StreamEvent], None],
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.t, self.cfg, self.on_event, self._now = transport, config, on_event, now
        self.state = ConnectionState.DISCONNECTED
        self.subscriptions: Dict[Tuple[str, str], SubscriptionSpec] = {}
        self.confirmed: Set[Tuple[str, str]] = set()
        self.last_message_at: Optional[datetime] = None
        self.reconnects = 0
        self.duplicates = 0
        self._seen: List[Tuple] = []
        self._seen_set: Set[Tuple] = set()

    # ── 連線 ──
    def connect(self) -> None:
        self.state = ConnectionState.CONNECTING
        self.t.open()
        self.t.send(self.t.auth_message())

    def disconnect(self) -> None:
        self.t.close()
        self.state = ConnectionState.CLOSED
        self.confirmed.clear()

    def reconnect(self) -> None:
        """斷線後：重新連線、重新登入，登入成功後自動重送所有訂閱（resubscribe）。"""
        self.reconnects += 1
        self.confirmed.clear()
        try:
            self.t.close()
        finally:
            self.connect()

    # ── 訂閱 ──
    @property
    def subscription_count(self) -> int:
        return len(self.subscriptions)

    def subscribe(self, spec: SubscriptionSpec) -> None:
        if spec.key() in self.subscriptions:
            return
        if self.subscription_count >= self.cfg.subscription_limit:
            raise SubscriptionLimitExceeded(f"訂閱已達上限 {self.cfg.subscription_limit}")
        self.subscriptions[spec.key()] = spec
        if self.state == ConnectionState.AUTHENTICATED:
            self.t.send(self.t.subscribe_message(spec))

    def unsubscribe(self, spec: SubscriptionSpec) -> None:
        if self.subscriptions.pop(spec.key(), None) is not None:
            self.confirmed.discard(spec.key())
            if self.state == ConnectionState.AUTHENTICATED:
                self.t.send(self.t.unsubscribe_message(spec))

    def _resubscribe_all(self) -> None:
        for spec in self.subscriptions.values():
            self.t.send(self.t.subscribe_message(spec))

    # ── 收訊息 ──
    def handle(self, raw: Dict[str, Any]) -> None:
        now = self._now()
        self.last_message_at = now
        kind, ev = self.t.parse(raw, now)
        if kind == "authenticated":
            self.state = ConnectionState.AUTHENTICATED
            self._resubscribe_all()
        elif kind == "subscribed" and ev is not None:
            self.confirmed.add((ev.channel, ev.symbol))
        elif kind == "heartbeat" and self.state == ConnectionState.STALE:
            self.state = ConnectionState.AUTHENTICATED
        elif kind == "data" and ev is not None:
            k = ev.dedupe_key()
            if k in self._seen_set:
                self.duplicates += 1
                return
            self._seen.append(k)
            self._seen_set.add(k)
            if len(self._seen) > self.cfg.dedupe_window:
                self._seen_set.discard(self._seen.pop(0))
            self.on_event(ev)

    def check_heartbeat(self) -> ConnectionState:
        """定時呼叫：太久沒收到任何訊息 → STALE（畫面要改標「推送中斷」，並安排 reconnect）。"""
        if self.state == ConnectionState.AUTHENTICATED and self.last_message_at is not None:
            if self._now() - self.last_message_at > timedelta(seconds=self.cfg.heartbeat_timeout_seconds):
                self.state = ConnectionState.STALE
        return self.state
