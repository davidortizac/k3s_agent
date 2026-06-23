"""Visor de histórico de sesiones (solo lectura, auditoría)."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

from ..config import Config
from ..history import list_sessions, read_session

EVENT_STYLE = {
    "user": ("❯", "bold cyan"),
    "assistant": ("🤖", "white"),
    "command": ("$", "green"),
    "blocked": ("🛑", "red"),
    "cancelled": ("⊘", "yellow"),
    "remember": ("🧠", "magenta"),
    "diagnose": ("🩺", "blue"),
    "error": ("✗", "red"),
    "meta": ("·", "dim"),
}


class HistoryView(ModalScreen[None]):
    DEFAULT_CSS = """
    HistoryView { align: center middle; }
    HistoryView > Vertical {
        width: 95%; height: 95%; padding: 1 2;
        border: thick $primary; background: $surface;
    }
    HistoryView .title { text-style: bold; color: $primary; margin-bottom: 1; }
    HistoryView #cols { height: 1fr; }
    HistoryView #sessions { width: 40%; border: round $panel; }
    HistoryView #detail { width: 60%; border: round $panel; padding: 0 1; }
    """

    BINDINGS = [
        ("escape", "close", "Cerrar"),
        ("c", "filter_commands", "Solo comandos"),
        ("m", "filter_mutations", "Solo modificaciones"),
        ("a", "filter_all", "Todo"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._sessions: list[dict] = []
        self._current_events: list[dict] = []
        self._filter = "all"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("📜 Histórico de sesiones (auditoría, no se reinyecta)", classes="title")
            with Horizontal(id="cols"):
                yield ListView(id="sessions")
                with VerticalScroll(id="detail"):
                    yield Static("Selecciona una sesión.  Filtros: [c] comandos · [m] modificaciones · [a] todo", id="detail_body")

    def on_mount(self) -> None:
        self._sessions = list_sessions(self.config.sessions_dir)
        lv = self.query_one("#sessions", ListView)
        if not self._sessions:
            lv.append(ListItem(Static("[dim](sin sesiones)[/]")))
            return
        for s in self._sessions:
            started = (s.get("started") or "")[:19].replace("T", " ")
            label = f"{s['id']}\n[dim]{started} · {s['commands']} cmd · {s['mutations']} mod[/]"
            lv.append(ListItem(Static(label)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.query_one("#sessions", ListView).index
        if idx is None or idx >= len(self._sessions):
            return
        self._current_events = read_session(self._sessions[idx]["path"])
        self._render_detail()

    def _render_detail(self) -> None:
        body = self.query_one("#detail_body", Static)
        out = Text()
        for ev in self._current_events:
            etype = ev.get("type", "?")
            if self._filter == "commands" and etype != "command":
                continue
            if self._filter == "mutations" and not (etype == "command" and ev.get("classification") == "mutating"):
                continue
            icon, style = EVENT_STYLE.get(etype, ("·", "dim"))
            ts = (ev.get("t") or "")[11:19]
            out.append(f"{ts} {icon} ", "dim")
            if etype in ("user", "assistant"):
                out.append((ev.get("text", "") or "").strip() + "\n", style)
            elif etype == "command":
                ok = "" if ev.get("ok", True) else " [FALLÓ]"
                out.append(f"{ev.get('command', '')}{ok}\n", style)
            elif etype in ("blocked", "cancelled"):
                out.append(f"{ev.get('command', '')} — {ev.get('reason', 'cancelado')}\n", style)
            elif etype == "meta":
                out.append(f"{ {k: v for k, v in ev.items() if k not in ('t', 'type')} }\n", style)
            else:
                out.append(str({k: v for k, v in ev.items() if k not in ('t', 'type')}) + "\n", style)
        body.update(out if out else Text("(vacío con este filtro)", style="dim"))

    def action_filter_commands(self) -> None:
        self._filter = "commands"
        self._render_detail()

    def action_filter_mutations(self) -> None:
        self._filter = "mutations"
        self._render_detail()

    def action_filter_all(self) -> None:
        self._filter = "all"
        self._render_detail()

    def action_close(self) -> None:
        self.dismiss(None)
