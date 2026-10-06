import asyncio

import pytest

from autosre.agents.base import PolicyViolation, validate_changes
from autosre.agents.code_agent import CodeAgent
from autosre.agents.healing_agent import HealingAgent
from autosre.agents.security_agent import bump_requirements
from autosre.config import Settings
from autosre.llm import extract_json
from autosre.state import StateStore


class FakeHub:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    async def call(self, tool, **args):
        self.calls.append((tool, args))
        r = self.responses[tool]
        return r(args) if callable(r) else r


class FakeLLM:
    def __init__(self, out):
        self.out = out

    def ask_json(self, system, prompt, max_tokens=4096):
        return self.out


def test_extract_json_handles_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": 2} tail') == {"a": 2}


def test_policy_blocks_protected_and_traversal():
    s = Settings()
    with pytest.raises(PolicyViolation):
        validate_changes([{"path": ".gitlab-ci.yml", "content": "x"}], s)
    with pytest.raises(PolicyViolation):
        validate_changes([{"path": "../etc/passwd", "content": "x"}], s)
    with pytest.raises(PolicyViolation):
        validate_changes([{"path": "autosre/hub.py", "content": "x"}], s)
    assert validate_changes([{"path": "app/new.py", "content": "x"}], s)[0]["file_path"] == "app/new.py"


def test_bump_requirements():
    out = bump_requirements("fastapi==0.1.0\nuvicorn==0.30.6\n", [{"name": "fastapi", "fix": "0.2.0"}])
    assert "fastapi==0.2.0" in out and "uvicorn==0.30.6" in out


def test_code_agent_end_to_end(tmp_path):
    hub = FakeHub({
        "get_issue": {"iid": 7, "title": "Add ping", "description": "d", "labels": []},
        "list_files": {"files": ["app/main.py"]},
        "read_file": {"content": "print(1)"},
        "create_branch": {"branch": "b"},
        "commit_files": {"sha": "abc"},
        "create_merge_request": {"iid": 3, "web_url": "u"},
        "auto_merge": {"auto_merge": True},
    })
    llm = FakeLLM({"summary": "s", "files": [{"path": "app/main.py", "action": "create", "content": "x"}]})
    agent = CodeAgent(hub=hub, llm=llm, state=StateStore(str(tmp_path / "s.json")), settings=Settings())
    res = asyncio.run(agent.run(7))
    assert res["branch"].startswith("autosre/7-add-ping")
    commit = next(a for t, a in hub.calls if t == "commit_files")
    assert commit["actions"][0]["action"] == "update"  # normalised against real tree
    assert ("auto_merge", {"mr_iid": 3}) in hub.calls


def test_healing_budget_escalates(tmp_path):
    hub = FakeHub({
        "get_failed_jobs": {"jobs": [{"id": 1, "name": "test", "stage": "verify", "trace_tail": "boom"}]},
        "create_issue": {"iid": 9, "web_url": "u"},
    })
    st = StateStore(str(tmp_path / "s.json"))
    st.set("heal:br", 3)
    agent = HealingAgent(hub=hub, llm=FakeLLM({}), state=st, settings=Settings())
    res = asyncio.run(agent.run(1, "br"))
    assert res["reason"] == "budget exhausted"


def test_healing_applies_patch(tmp_path):
    hub = FakeHub({
        "get_failed_jobs": {"jobs": [{"id": 1, "name": "test", "stage": "verify",
                                      "trace_tail": "File app/main.py line 3 NameError"}]},
        "read_file": {"content": "bad"},
        "commit_files": {"sha": "z"},
    })
    llm = FakeLLM({"kind": "code", "diagnosis": "d", "summary": "fix", "files": [
        {"path": "app/main.py", "action": "update", "content": "good"}]})
    agent = HealingAgent(hub=hub, llm=llm, state=StateStore(str(tmp_path / "s.json")), settings=Settings())
    res = asyncio.run(agent.run(1, "br"))
    assert res["healed"] and any(t == "commit_files" for t, _ in hub.calls)
