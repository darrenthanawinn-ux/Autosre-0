"""Claude wrapper. All agent reasoning goes through ask_json for structured, validated output."""
import json
import re
from typing import Any, Protocol

from .config import get_settings


class LLM(Protocol):
    def ask_json(self, system: str, prompt: str, max_tokens: int = 4096) -> Any: ...


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class ClaudeLLM:
    def __init__(self):
        import anthropic

        s = get_settings()
        self.model = s.anthropic_model
        self.client = anthropic.Anthropic(api_key=s.anthropic_key or None)

    def ask_json(self, system: str, prompt: str, max_tokens: int = 4096) -> Any:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system + "\nRespond with a single valid JSON object only. No prose.",
            messages=[{"role": "user", "content": prompt}],
        )
        return extract_json("".join(b.text for b in msg.content if b.type == "text"))
