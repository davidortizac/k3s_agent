"""TUI Textual estilo Claude Code: entrypoint de la aplicación.

El motor (síncrono) corre en un worker-thread. Los callbacks del motor llegan a la
UI a través de `UIHooks`, que reenvía cada mutación al hilo de UI con
`call_from_thread`. La confirmación de operaciones mutating bloquea el worker con un
`threading.Event` hasta que el usuario responde en el modal.
"""

from __future__ import annotations

import threading
from typing import Iterable

from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.screen import Screen
from textual.widgets import Footer, Input

from .config import Config, load_config
from .diagnose import run_local_diagnose
from .engine import Engine, EngineHooks
from .history import History
from .memory import Memory
from .tools.base import ToolResult, build_registry
from .ui.confirm import ConfirmModal
from .ui.conversation import ConversationView
from .ui.history_view import HistoryView
from .ui.memory_view import MemoryView
from .ui.statusbar import StatusBar
from .ui.tools_view import ToolsView

HELP_TEXT = """\
**Comandos disponibles**

- `/diag` — diagnóstico rápido local (sin LLM): nodos y pods con problemas.
- `/memory` — ver/añadir/borrar notas de memoria persistente.
- `/history` — explorar sesiones pasadas (auditoría).
- `/tools` — herramientas cargadas y su estado.
- `/model <id>` — cambiar el modelo en caliente.
- `/readonly` — alternar modo solo-lectura.
- `/clear` — limpiar la conversación actual.
- `/help` — esta ayuda.
- `/quit` — salir.

Escribe en lenguaje natural para hablar con el agente. Las operaciones que
modifican el cluster piden confirmación (`y`/`n`) en un modal.
"""


class UIHooks(EngineHooks):
    """Adaptador de hooks del motor → mutaciones de la UI (thread-safe)."""

    def __init__(self, app: "K3sctlApp"):
        self.app = app

    @property
    def _conv(self) -> ConversationView:
        return self.app.query_one(ConversationView)

    def _dispatch(self, fn, *args) -> None:
        """Ejecuta fn en el hilo de UI: directo si ya estamos en él, vía
        call_from_thread si nos llaman desde el worker del agente."""
        if threading.get_ident() == getattr(self.app, "_thread_id", None):
            fn(*args)
        else:
            self.app.call_from_thread(fn, *args)

    def on_assistant_delta(self, text: str) -> None:
        self._dispatch(self._conv.add_assistant_delta, text)

    def on_assistant_message(self, text: str) -> None:
        self._dispatch(self._conv.add_assistant_message, text)

    def on_tool_start(self, call_id, tool, display, classification, reason) -> None:
        self._dispatch(self._conv.add_tool_card, call_id, display, classification, reason)

    def on_tool_result(self, call_id, result: ToolResult) -> None:
        self._dispatch(self._conv.update_tool_result, call_id, result.ok, result.output)

    def on_tool_blocked(self, call_id, display, reason) -> None:
        self._dispatch(self._conv.mark_tool_blocked, call_id, reason)

    def on_error(self, message: str) -> None:
        self._dispatch(self._conv.add_notice, f"⚠ {message}", "red")

    def on_status(self, info: dict) -> None:
        self._dispatch(self.app.query_one(StatusBar).update_status, info)

    def confirm(self, tool: str, display: str, reason: str) -> bool:
        """Bloquea el worker hasta que el usuario decida en el modal."""
        event = threading.Event()
        result = {"value": False}

        def push() -> None:
            def on_dismiss(value: bool | None) -> None:
                result["value"] = bool(value)
                event.set()

            self.app.push_screen(ConfirmModal(tool, display, reason), on_dismiss)

        self.app.call_from_thread(push)
        event.wait()
        return result["value"]


class K3sctlApp(App):
    TITLE = "k3sctl"
    SUB_TITLE = "agente k3s"

    CSS = """
    Screen { layers: base; }
    #input { dock: bottom; border: round $primary; margin: 0 1 1 1; }
    .notice { padding: 0 1; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Salir"),
        ("ctrl+l", "clear", "Limpiar"),
        ("ctrl+r", "toggle_readonly", "Read-only"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.memory = Memory(config.memory_path)
        self.history = History(config.sessions_dir)
        self.registry = build_registry(config)
        self.hooks = UIHooks(self)
        self.engine = Engine(config, self.registry, self.memory, self.history, self.hooks)
        self._cmd_history: list[str] = []
        self._hist_pos: int | None = None
        self._busy = False

    # -- layout -------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield ConversationView()
        yield StatusBar()
        yield Input(placeholder="Pregunta o instrucción…  (/help para comandos)", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(ConversationView).add_notice(
            f"k3sctl listo · modelo {self.config.model} · {self.config.base_url}", "green"
        )
        self.engine._emit_status()
        self.query_one("#input", Input).focus()

    # -- command palette ----------------------------------------------------
    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Diagnóstico (/diag)", "Diagnóstico local sin LLM", self.action_diag)
        yield SystemCommand("Memoria (/memory)", "Ver y editar notas persistentes", self.action_memory)
        yield SystemCommand("Histórico (/history)", "Explorar sesiones pasadas", self.action_history)
        yield SystemCommand("Tools (/tools)", "Herramientas cargadas", self.action_tools)
        yield SystemCommand("Solo-lectura (toggle)", "Activa/desactiva read-only", self.action_toggle_readonly)
        yield SystemCommand("Limpiar conversación", "Vacía el contexto", self.action_clear)

    # -- entrada ------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        inp = self.query_one("#input", Input)
        inp.value = ""
        if not text:
            return
        self._cmd_history.append(text)
        self._hist_pos = None

        if text.startswith("/"):
            self._handle_slash(text)
            return

        if self._busy:
            self.query_one(ConversationView).add_notice("Espera a que termine el turno actual.", "yellow")
            return

        self.query_one(ConversationView).add_user(text)
        self._set_busy(True)
        self._run_agent(text)

    def on_key(self, event) -> None:
        # Historial de comandos con flechas, solo si el input tiene foco.
        if not self.query_one("#input", Input).has_focus:
            return
        if event.key not in ("up", "down") or not self._cmd_history:
            return
        if event.key == "up":
            self._hist_pos = len(self._cmd_history) - 1 if self._hist_pos is None else max(0, self._hist_pos - 1)
        else:
            if self._hist_pos is None:
                return
            self._hist_pos = min(len(self._cmd_history) - 1, self._hist_pos + 1)
        inp = self.query_one("#input", Input)
        inp.value = self._cmd_history[self._hist_pos]
        inp.cursor_position = len(inp.value)
        event.prevent_default()

    # -- worker del agente --------------------------------------------------
    @work(thread=True, exclusive=True, group="agent")
    def _run_agent(self, text: str) -> None:
        try:
            self.engine.run_turn(text)
        finally:
            self.call_from_thread(self._set_busy, False)

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        inp = self.query_one("#input", Input)
        inp.disabled = value
        inp.placeholder = "Pensando…" if value else "Pregunta o instrucción…  (/help para comandos)"
        if not value:
            inp.focus()

    # -- slash commands -----------------------------------------------------
    def _handle_slash(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        conv = self.query_one(ConversationView)

        if cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/help":
            conv.add_assistant_message(HELP_TEXT)
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/diag":
            self.action_diag()
        elif cmd == "/memory":
            self.action_memory()
        elif cmd == "/history":
            self.action_history()
        elif cmd == "/tools":
            self.action_tools()
        elif cmd == "/readonly":
            self.action_toggle_readonly()
        elif cmd == "/model":
            if not arg:
                conv.add_notice(f"Modelo actual: {self.engine.config.model}", "cyan")
            else:
                self.engine.set_model(arg)
                conv.add_notice(f"Modelo cambiado a: {arg}", "green")
                self.engine._emit_status()
        else:
            conv.add_notice(f"Comando desconocido: {cmd}. Usa /help.", "yellow")

    # -- acciones -----------------------------------------------------------
    def action_clear(self) -> None:
        self.engine.clear()
        conv = self.query_one(ConversationView)
        conv.remove_children()
        conv.add_notice("Conversación limpiada.", "green")

    def action_toggle_readonly(self) -> None:
        new = not self.engine.config.read_only
        self.engine.set_read_only(new)
        self.engine._emit_status()
        self.query_one(ConversationView).add_notice(
            f"Modo solo-lectura {'ACTIVADO' if new else 'desactivado'}.",
            "red" if new else "green",
        )

    def action_memory(self) -> None:
        self.push_screen(MemoryView(self.memory), lambda _=None: self.engine._emit_status())

    def action_history(self) -> None:
        self.push_screen(HistoryView(self.config))

    def action_tools(self) -> None:
        self.push_screen(ToolsView(self.registry))

    @work(thread=True, group="diag")
    def action_diag(self) -> None:
        self.call_from_thread(
            self.query_one(ConversationView).add_notice, "Ejecutando diagnóstico local…", "cyan"
        )
        report = run_local_diagnose(self.engine.config, self.memory)
        self.history.log("diagnose", summary=report[:500])
        self.call_from_thread(self.query_one(ConversationView).add_assistant_message, f"```\n{report}\n```")


def main(argv: list[str] | None = None) -> None:
    config = load_config(argv)
    config.home.mkdir(parents=True, exist_ok=True)
    app = K3sctlApp(config)
    app.run()


if __name__ == "__main__":
    main()
