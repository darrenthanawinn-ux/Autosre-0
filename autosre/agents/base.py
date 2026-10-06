"""Shared agent base + governance guardrails."""
import logging
import posixpath
from dataclasses import dataclass
from typing import ClassVar

from ..config import Settings
from ..hub import ToolHub
from ..llm import LLM
from ..state import StateStore

log = logging.getLogger("autosre")


class PolicyViolation(Exception):
    pass


def validate_changes(changes: list[dict], settings: Settings) -> list[dict]:
    """Governance gate: reject path traversal and edits to protected control-plane files."""
    clean = []
    for c in changes:
        path = posixpath.normpath(str(c.get("path", "")))
        if path.startswith(("/", "..")) or ".." in path.split("/"):
            raise PolicyViolation(f"unsafe path: {path}")
        if any(path == p or path.startswith(p) for p in settings.protected_paths):
            raise PolicyViolation(f"protected path: {path}")
        action = c.get("action", "update")
        if action not in ("create", "update", "delete"):
            raise PolicyViolation(f"bad action: {action}")
        clean.append({"action": action, "file_path": path, "content": c.get("content", "")})
    return clean


@dataclass
class Agent:
    hub: ToolHub
    llm: LLM
    state: StateStore
    settings: Settings
    name: ClassVar[str] = "agent"

    def say(self, msg: str) -> None:
        log.info("[%s] %s", self.name, msg)
        print(f"[{self.name}] {msg}", flush=True)
