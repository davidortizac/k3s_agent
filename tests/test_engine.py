"""Test del bucle agéntico con un cliente LLM falso (sin red).

Valida la acumulación de tool_calls fragmentados en el stream y el encadenamiento
turno→tool→turno hasta que el modelo deja de pedir herramientas.
"""

from types import SimpleNamespace

from k3sctl.config import Config
from k3sctl.engine import Engine, EngineHooks
from k3sctl.history import History
from k3sctl.memory import Memory
from k3sctl.tools.base import build_registry


def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tc_delta(index, id=None, name=None, args=None):
    fn = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=index, id=id, function=fn)


class FakeCompletions:
    def __init__(self, scripted):
        self._scripted = scripted
        self.calls = 0

    def create(self, **kwargs):
        streams = self._scripted[self.calls]
        self.calls += 1
        return iter(streams)


class FakeClient:
    def __init__(self, scripted):
        self.chat = SimpleNamespace(completions=FakeCompletions(scripted))


class CollectHooks(EngineHooks):
    def __init__(self):
        self.deltas = []
        self.messages = []
        self.tools_started = []

    def on_assistant_delta(self, text):
        self.deltas.append(text)

    def on_assistant_message(self, text):
        self.messages.append(text)

    def on_tool_start(self, call_id, tool, display, classification, reason):
        self.tools_started.append((tool, classification, display))

    def confirm(self, tool, display, reason):
        return True  # aprobar todo (no debería pedirse para lecturas)


def test_streaming_toolcall_then_final(tmp_path, monkeypatch):
    cfg = Config(home=tmp_path)
    hooks = CollectHooks()
    eng = Engine(cfg, build_registry(cfg), Memory(cfg.memory_path), History(cfg.sessions_dir), hooks)

    # Turno 1: el modelo pide remember (read, no confirma) con args fragmentados.
    turn1 = [
        _chunk(content="Voy a anotar eso. "),
        _chunk(tool_calls=[_tc_delta(0, id="c1", name="remember")]),
        _chunk(tool_calls=[_tc_delta(0, args='{"note":"Long')]),
        _chunk(tool_calls=[_tc_delta(0, args='horn por defecto"}')]),
    ]
    # Turno 2: respuesta final, sin tools.
    turn2 = [_chunk(content="Hecho.")]

    eng.client = FakeClient([turn1, turn2])
    eng.run_turn("recuerda que Longhorn es la SC por defecto")

    # Se ejecutó la tool remember y persistió la nota.
    assert ("remember", "read", None) != hooks.tools_started  # sanity
    assert hooks.tools_started[0][0] == "remember"
    assert eng.memory.count() == 1
    assert "Longhorn" in eng.memory.notes()[0]["note"]

    # Texto en streaming + mensaje final.
    assert "".join(hooks.deltas).startswith("Voy a anotar")
    assert hooks.messages[-1] == "Hecho."

    # La conversación termina con el assistant final (sin tool_calls pendientes).
    assert eng.messages[-1]["role"] == "assistant"
    assert eng.messages[-1]["content"] == "Hecho."
    # Hubo exactamente 2 llamadas al LLM.
    assert eng.client.chat.completions.calls == 2
