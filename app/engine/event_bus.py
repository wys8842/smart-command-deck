"""事件总线（M2）：持久化队列 + 已处理去重（append-only JSONL，O(1) 写入）。

存储格式：每行一个 JSON
    {"_t":"e", ...Event...}        事件
    {"_t":"p","ev_id":"..."}       已处理标记
兼容读取旧的单文件 JSON 格式（首次加载后自动转写为 JSONL）。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Event:
    ev_id: str
    kind: str
    source: str
    ts: str
    round: int = 1
    payload: dict = field(default_factory=dict)
    seq: int = 0


def new_event(kind: str, source: str, payload: dict, round: int = 1) -> Event:
    return Event(
        ev_id=f"ev-{uuid.uuid4().hex[:12]}",
        kind=kind,
        source=source,
        ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
        round=round,
        payload=payload,
    )


class EventBus:
    """简单持久化事件总线（单机 append-only JSONL）。"""

    def __init__(self, path: str = "data/events.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[dict] = []
        self._processed: set[str] = set()
        self._ids: set[str] = set()          # O(1) 去重
        self._fh = None                       # 持久 append 句柄（降低开/关开销）
        self._load()

    # ---------------- 加载/持久化 ----------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8")
        stripped = text.lstrip()
        # 旧格式：整文件一个 JSON 对象
        if stripped.startswith("{"):
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "events" in data:
                    self._events = list(data.get("events", []))
                    self._processed = set(data.get("processed", []))
                    self._ids = {e.get("ev_id") for e in self._events}
                    self._rewrite()
                    return
            except json.JSONDecodeError:
                pass
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("_t") == "p":
                self._processed.add(rec.get("ev_id"))
            else:
                rec.pop("_t", None)
                self._events.append(rec)
                self._ids.add(rec.get("ev_id"))

    def _append_line(self, rec: dict) -> None:
        if self._fh is None:
            self._fh = self.path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None

    def _rewrite(self) -> None:
        self.close()
        with self.path.open("w", encoding="utf-8") as f:
            for e in self._events:
                f.write(json.dumps({"_t": "e", **e}, ensure_ascii=False) + "\n")
            for ev_id in self._processed:
                f.write(json.dumps({"_t": "p", "ev_id": ev_id}, ensure_ascii=False) + "\n")

    # ---------------- 公共 API ----------------

    def enqueue(self, event: Event) -> Event:
        if event.ev_id not in self._ids:
            event.seq = len(self._events) + 1
            rec = asdict(event)
            self._events.append(rec)
            self._ids.add(event.ev_id)
            self._append_line({"_t": "e", **rec})
        return event

    def receipt(self, ev_id: str) -> dict | None:
        rec = next((e for e in self._events if e.get("ev_id") == ev_id), None)
        if rec is None:
            return None
        return {
            "ev_id": ev_id,
            "seq": rec.get("seq", 0),
            "kind": rec.get("kind"),
            "status": "processed" if ev_id in self._processed else "queued",
        }

    def list_receipts(self, limit: int = 50, offset: int = 0) -> list[dict]:
        out = []
        for rec in self._events:
            out.append({
                "ev_id": rec.get("ev_id"),
                "seq": rec.get("seq", 0),
                "kind": rec.get("kind"),
                "source": rec.get("source"),
                "ts": rec.get("ts"),
                "status": "processed" if rec.get("ev_id") in self._processed else "queued",
            })
        return list(reversed(out))[offset: offset + limit]

    def pending(self) -> list[Event]:
        return [Event(**e) for e in self._events if e["ev_id"] not in self._processed]

    def mark_processed(self, ev_id: str) -> None:
        if ev_id not in self._processed:
            self._processed.add(ev_id)
            self._append_line({"_t": "p", "ev_id": ev_id})

    def is_processed(self, ev_id: str) -> bool:
        return ev_id in self._processed

    def reset(self) -> None:
        self._events = []
        self._processed = set()
        self._rewrite()


__all__ = ["Event", "EventBus", "new_event"]
