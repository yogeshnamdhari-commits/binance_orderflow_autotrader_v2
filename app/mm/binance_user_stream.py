from __future__ import annotations

import json
import os
import threading
import time
import uuid

import websocket

from .user_stream import UserStreamGuard


class BinanceUSDMUserStream:
    """Authenticated USD-M user-data stream with explicit keepalive/reconnect."""

    CONTROL_URL = "wss://ws-fapi.binance.com/ws-fapi/v1"
    PRIVATE_STREAM_BASE = "wss://fstream.binance.com/private/ws"

    def __init__(self, api_key: str | None = None, *, guard: UserStreamGuard | None = None,
                 event_cb=None, status_cb=print):
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("BINANCE_API_KEY is required")
        self.guard = guard or UserStreamGuard()
        self.event_cb = event_cb or (lambda _event: None)
        self.status_cb = status_cb
        self.stop_flag = False
        self.listen_key: str | None = None
        self._private_ws = None
        self._control_lock = threading.Lock()
        self._last_keepalive_ms = 0

    def _control_call(self, method: str) -> str | None:
        response: dict = {}
        ws = websocket.create_connection(
            self.CONTROL_URL,
            timeout=5,
            header=[f"X-MBX-APIKEY: {self.api_key}"],
            enable_multithread=True,
        )
        try:
            request_id = str(uuid.uuid4())
            ws.send(json.dumps({
                "id": request_id,
                "method": method,
                "params": {"apiKey": self.api_key},
            }))
            deadline = time.time() + 5
            while time.time() < deadline:
                ws.settimeout(max(0.1, deadline - time.time()))
                payload = json.loads(ws.recv())
                if payload.get("id") == request_id:
                    response = payload
                    break
            if response.get("status") != 200:
                raise RuntimeError(
                    f"user_stream_control_failed:{method}:{response.get('status')}:{response.get('error')}"
                )
            if method == "userDataStream.stop":
                return None
            return str((response.get("result") or {}).get("listenKey"))
        finally:
            ws.close()

    def start_stream(self) -> str:
        with self._control_lock:
            listen_key = self._control_call("userDataStream.start")
            if not listen_key:
                raise RuntimeError("user_stream_start_missing_listen_key")
            self.listen_key = listen_key
            self._last_keepalive_ms = int(time.time() * 1000)
            return listen_key

    def keepalive(self) -> str:
        with self._control_lock:
            listen_key = self._control_call("userDataStream.ping")
            if listen_key:
                self.listen_key = listen_key
            self._last_keepalive_ms = int(time.time() * 1000)
            return self.listen_key or ""

    def stop_stream(self) -> None:
        with self._control_lock:
            try:
                self._control_call("userDataStream.stop")
            finally:
                self.listen_key = None
                self.guard.disconnected()

    def _touch_transport(self) -> None:
        self.guard.heartbeat(int(time.time() * 1000))

    def _on_message(self, ws, raw: str) -> None:
        payload = json.loads(raw)
        self._touch_transport()
        event_type = payload.get("e")
        event_ts = int(payload.get("E", int(time.time() * 1000)))
        if event_type == "listenKeyExpired":
            self.listen_key = None
            self.guard.disconnected()
            self.status_cb({"status": "LISTEN_KEY_EXPIRED"})
            try:
                ws.close()
            except Exception:
                pass
            return
        if event_type == "MARGIN_CALL":
            self.guard.disconnected()
            self.status_cb({"status": "MARGIN_CALL"})
            return
        try:
            parsed = self.guard.parse(payload)
            for event in parsed:
                self.event_cb(event)
            self.guard.connected_event(event_ts)
        except Exception as exc:
            self.guard.disconnected()
            self.status_cb({"status": "USER_STREAM_PARSE_ERROR", "error": repr(exc)})
            raise

    def _on_open(self, _ws) -> None:
        self.guard.connected_event(int(time.time() * 1000))
        self.status_cb({"status": "USER_STREAM_CONNECTED"})

    def _on_ping(self, _ws, _message) -> None:
        self._touch_transport()

    def _on_pong(self, _ws, _message) -> None:
        self._touch_transport()

    def _on_error(self, _ws, error) -> None:
        self.guard.disconnected()
        self.status_cb({"status": "USER_STREAM_ERROR", "error": repr(error)})

    def _on_close(self, _ws, *_args) -> None:
        self.guard.disconnected()
        self.status_cb({"status": "USER_STREAM_CLOSED"})

    def _keepalive_loop(self) -> None:
        while not self.stop_flag:
            now = int(time.time() * 1000)
            if self.listen_key and now - self._last_keepalive_ms >= 45 * 60 * 1000:
                try:
                    self.keepalive()
                    self.status_cb({"status": "USER_STREAM_KEEPALIVE"})
                except Exception as exc:
                    self.listen_key = None
                    self.guard.disconnected()
                    self.status_cb({"status": "USER_STREAM_KEEPALIVE_FAILED", "error": repr(exc)})
                    if self._private_ws is not None:
                        try:
                            self._private_ws.close()
                        except Exception:
                            pass
            time.sleep(5)

    def run(self) -> None:
        self.start_stream()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()
        backoff = 1.0
        while not self.stop_flag:
            try:
                if not self.listen_key:
                    self.start_stream()
                url = f"{self.PRIVATE_STREAM_BASE}?listenKey={self.listen_key}&events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE"
                self._private_ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_ping=self._on_ping,
                    on_pong=self._on_pong,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._private_ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                self.guard.disconnected()
                self.status_cb({"status": "USER_STREAM_RUN_ERROR", "error": repr(exc)})
            if self.stop_flag:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def stop(self) -> None:
        self.stop_flag = True
        try:
            if self._private_ws is not None:
                self._private_ws.close()
        finally:
            if self.listen_key:
                try:
                    self.stop_stream()
                except Exception:
                    self.guard.disconnected()
