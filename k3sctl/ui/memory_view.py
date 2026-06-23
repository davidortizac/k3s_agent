"""Visor/editor de memoria persistente (conocimiento ESTABLE del cluster)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from ..memory import Memory


class MemoryView(ModalScreen[None]):
    DEFAULT_CSS = """
    MemoryView { align: center middle; }
    MemoryView > Vertical {
        width: 90%; height: 90%; padding: 1 2;
        border: thick $primary; background: $surface;
    }
    MemoryView .title { text-style: bold; color: $primary; }
    MemoryView .hint { color: $text-muted; margin-bottom: 1; }
    MemoryView ListView { height: 1fr; border: round $panel; }
    MemoryView #bar { height: auto; }
    """

    BINDINGS = [
        ("escape", "close", "Cerrar"),
        ("d", "delete", "Borrar nota"),
        ("ctrl+f", "focus_search", "Buscar"),
    ]

    def __init__(self, memory: Memory):
        super().__init__()
        self.memory = memory
        self._filtered_indices: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("🧠 Memoria persistente — conocimiento estable del cluster", classes="title")
            yield Static(
                "Separado del histórico de sesión. [d] borrar · [Esc] cerrar · escribe y Enter para añadir/buscar.",
                classes="hint",
            )
            yield ListView(id="notes")
            with Horizontal(id="bar"):
                yield Input(placeholder="Nueva nota… (Enter) o buscar con Ctrl+F", id="note_input")
                yield Button("Añadir", variant="success", id="add")
                yield Button("Buscar", id="search")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self, query: str = "") -> None:
        lv = self.query_one("#notes", ListView)
        lv.clear()
        notes = self.memory.notes()
        self._filtered_indices = []
        for i, n in enumerate(notes):
            text = n.get("note", "")
            if query and query.lower() not in text.lower():
                continue
            self._filtered_indices.append(i)
            ts = n.get("t", "")[:19].replace("T", " ")
            lv.append(ListItem(Static(f"[dim]{ts}[/]  {text}")))
        if not self._filtered_indices:
            lv.append(ListItem(Static("[dim](sin notas)[/]")))

    # -- acciones -----------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        inp = self.query_one("#note_input", Input)
        if event.button.id == "add":
            self._add(inp.value)
        elif event.button.id == "search":
            self._refresh(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter en el input = añadir nota.
        self._add(event.value)

    def _add(self, value: str) -> None:
        value = value.strip()
        if value:
            self.memory.add(value)
        self.query_one("#note_input", Input).value = ""
        self._refresh()

    def action_delete(self) -> None:
        lv = self.query_one("#notes", ListView)
        idx = lv.index
        if idx is None or idx >= len(self._filtered_indices):
            return
        real_index = self._filtered_indices[idx]
        self.memory.delete(real_index)
        self._refresh()

    def action_focus_search(self) -> None:
        self.query_one("#note_input", Input).focus()

    def action_close(self) -> None:
        self.dismiss(None)
