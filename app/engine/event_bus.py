"""事件总线（M2）：持久化的待处理队列 + 已处理去重。

单机 JSON 文件实现；事件契约：
Event(ev_id, kind, source, ts, round, payload)
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
    """简单持久化事件总线（单机 JSON）。"""

    def __init__(self, path: str = "data/events.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, list] = self._load()

    def _load(self) -> dict[str, list]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"events": [], "processed": []}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def enqueue(self, event: Event) -> Event:
        if not any(e.get("ev_id") == event.ev_id for e in self._data["events"]):
            event.seq = len(self._data["events"]) + 1
            self._data["events"].append(asdict(event))
            self._save()
        return event

    def receipt(self, ev_id: str) -> dict | None:
        """回执：查某事件是否已入队/已处理。"""
        rec = next((e for e in self._data["events"] if e.get("ev_id") == ev_id), None)
        if rec is None:
            return None
        return {
            "ev_id": ev_id,
            "seq": rec.get("seq", 0),
            "kind": rec.get("kind"),
            "status": "processed" if ev_id in self._data["processed"] else "queued",
        }

    def list_receipts(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """列出事件回执（最新在前，支持分页）。"""
        processed = set(self._data["processed"])
        out = []
        for rec in self._data["events"]:
            out.append({
                "ev_id": rec.get("ev_id"),
                "seq": rec.get("seq", 0),
                "kind": rec.get("kind"),
                "source": rec.get("source"),
                "ts": rec.get("ts"),
                "status": "processed" if rec.get("ev_id") in processed else "queued",
            })
        ordered = list(reversed(out))
        return ordered[offset: offset + limit]

    def pending(self) -> list[Event]:
        processed = set(self._data["processed"])
        return [Event(**e) for e in self._data["events"] if e["ev_id"] not in processed]

    def mark_processed(self, ev_id: str) -> None:
        if ev_id not in self._data["processed"]:
            self._data["processed"].append(ev_id)
            self._save()

    def is_processed(self, ev_id: str) -> bool:
        return ev_id in self._data["processed"]

    def reset(self) -> None:
        self._data = {"events": [], "processed": []}
        self._save()


__all__ = ["Event", "EventBus", "new_event"]
