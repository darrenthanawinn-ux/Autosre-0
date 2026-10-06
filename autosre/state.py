"""Tiny JSON state store: carries context between agents and across CI pipelines."""
import json
import os
import threading
from typing import Any

_lock = threading.Lock()


class StateStore:
    def __init__(self, path: str):
        self.path = path

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path) as f:
            return json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        with _lock:
            return self._load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        with _lock:
            data = self._load()
            data[key] = value
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)

    def incr(self, key: str) -> int:
        n = int(self.get(key, 0)) + 1
        self.set(key, n)
        return n
