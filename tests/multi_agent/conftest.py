from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass
class FakeClock:
    now_s: float = 0.0

    def time(self) -> float:
        return self.now_s

    def advance(self, seconds: float) -> float:
        self.now_s += float(seconds)
        return self.now_s


class ControlledProvider:
    """Deterministic provider double that never reaches a remote model."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if not self.responses:
            raise AssertionError("ControlledProvider received an unexpected call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ControlledTool:
    """Deterministic tool double with visible call accounting."""

    def __init__(self, outputs: list[Any] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if not self.outputs:
            raise AssertionError("ControlledTool received an unexpected call")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


@pytest.fixture()
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def controlled_provider() -> ControlledProvider:
    return ControlledProvider()


@pytest.fixture()
def controlled_tool() -> ControlledTool:
    return ControlledTool()


@pytest.fixture()
def isolated_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give MAxx tests a disposable storage root and explicit local DB paths."""

    root = tmp_path / "aitrans-multi-agent"
    root.mkdir(parents=True, exist_ok=True)
    (root / "qdrant").mkdir()

    monkeypatch.setenv("AITRANS_DATA_ROOT", str(root))
    monkeypatch.setenv("AITRANS_TEST_DATA_ROOT", str(root))
    monkeypatch.setenv("AITRANS_QDRANT_PATH", str(root / "qdrant"))
    monkeypatch.setenv("AITRANS_AGENT_ARTIFACT_DB", str(root / "agent_artifacts.sqlite3"))
    return root


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """MA tests are offline by default; real-provider evaluation must opt in elsewhere."""

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("external network access is disabled in tests/multi_agent")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
