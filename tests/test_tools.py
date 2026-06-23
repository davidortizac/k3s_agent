"""Tests del sistema de tools, registro y políticas de seguridad del motor."""

from pathlib import Path

import pytest

from k3sctl.config import Config
from k3sctl.engine import Engine, EngineHooks
from k3sctl.history import History
from k3sctl.memory import Memory
from k3sctl.safety import MUTATING, READ
from k3sctl.tools.base import ToolCall, ToolContext, build_registry
from k3sctl.tools.file_read_tool import FileReadTool
from k3sctl.tools.kubectl_tool import KubectlTool
from k3sctl.tools.remember_tool import RememberTool


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(home=tmp_path, contexts=["dev", "qa"], default_context="dev")


# -- registro -----------------------------------------------------------------

def test_shell_disabled_by_default(cfg):
    reg = build_registry(cfg)
    assert "shell" in reg.tools
    assert reg.is_active("shell") is False


def test_enable_shell(cfg):
    reg = build_registry(cfg.with_overrides(enable=["shell"]))
    assert reg.is_active("shell") is True


def test_disable_helm(cfg):
    reg = build_registry(cfg.with_overrides(disable=["run_helm"]))
    assert reg.is_active("run_helm") is False


# -- clasificación por tool ---------------------------------------------------

def test_kubectl_classify():
    kt = KubectlTool()
    assert kt.classify(ToolCall("run_kubectl", {"args": ["get", "pods"]})) == READ
    assert kt.classify(ToolCall("run_kubectl", {"args": ["delete", "pod", "x"]})) == MUTATING


def test_kubectl_context_allowlist_rejected(cfg):
    kt = KubectlTool()
    ctx = ToolContext(config=cfg, memory=Memory(cfg.memory_path))
    call = ToolCall("run_kubectl", {"args": ["get", "pods"], "context": "prod", "reason": "x"})
    res = kt.run(call, ctx)
    assert res.ok is False
    assert "no permitido" in res.output


def test_file_read(tmp_path, cfg):
    f = tmp_path / "m.yaml"
    f.write_text("kind: Pod\n", encoding="utf-8")
    res = FileReadTool().run(
        ToolCall("file_read", {"path": str(f)}), ToolContext(config=cfg, memory=Memory(cfg.memory_path))
    )
    assert res.ok and "kind: Pod" in res.output


def test_remember(cfg):
    mem = Memory(cfg.memory_path)
    RememberTool().run(ToolCall("remember", {"note": "Longhorn es la SC por defecto"}), ToolContext(cfg, mem))
    assert mem.count() == 1
    assert "Longhorn" in mem.notes()[0]["note"]


# -- políticas del motor ------------------------------------------------------

class RecordingHooks(EngineHooks):
    def __init__(self, approve: bool):
        self.approve = approve
        self.blocked = []
        self.results = []

    def on_tool_blocked(self, call_id, display, reason):
        self.blocked.append((display, reason))

    def on_tool_result(self, call_id, result):
        self.results.append(result)

    def confirm(self, tool, display, reason):
        return self.approve


def _engine(cfg, hooks):
    mem = Memory(cfg.memory_path)
    hist = History(cfg.sessions_dir)
    reg = build_registry(cfg)
    return Engine(cfg, reg, mem, hist, hooks)


def _mutating_call():
    return {
        "id": "c1",
        "type": "function",
        "function": {"name": "run_kubectl", "arguments": '{"args":["scale","deploy/api","--replicas=3"],"reason":"x"}'},
    }


def test_readonly_blocks_mutation(cfg):
    hooks = RecordingHooks(approve=True)
    eng = _engine(cfg.with_overrides(read_only=True), hooks)
    eng._handle_tool_call(_mutating_call())
    assert hooks.blocked, "una mutación en read-only debe bloquearse"
    assert "solo-lectura" in hooks.blocked[0][1].lower()
    # No se añadió un resultado de ejecución, sí un mensaje tool de BLOQUEADO.
    assert eng.messages[-1]["role"] == "tool"
    assert "BLOQUEADO" in eng.messages[-1]["content"]


def test_denied_confirmation_cancels(cfg):
    hooks = RecordingHooks(approve=False)
    eng = _engine(cfg, hooks)
    eng._handle_tool_call(_mutating_call())
    assert hooks.blocked
    assert "CANCELADO" in eng.messages[-1]["content"]


def test_invalid_json_args_does_not_crash(cfg):
    hooks = RecordingHooks(approve=True)
    eng = _engine(cfg, hooks)
    bad = {"id": "c2", "type": "function", "function": {"name": "run_kubectl", "arguments": "{not json"}}
    eng._handle_tool_call(bad)  # no debe lanzar
    assert eng.messages[-1]["role"] == "tool"
    assert "inválidos" in eng.messages[-1]["content"]
