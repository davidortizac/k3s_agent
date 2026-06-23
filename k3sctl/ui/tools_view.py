"""Visor de herramientas cargadas (/tools): estado activa/inactiva, segura/peligrosa."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from ..tools.base import ToolRegistry


class ToolsView(ModalScreen[None]):
    DEFAULT_CSS = """
    ToolsView { align: center middle; }
    ToolsView > Vertical {
        width: 80%; height: auto; max-height: 90%; padding: 1 2;
        border: thick $primary; background: $surface;
    }
    ToolsView .title { text-style: bold; color: $primary; margin-bottom: 1; }
    ToolsView DataTable { height: auto; }
    """

    BINDINGS = [("escape", "close", "Cerrar")]

    def __init__(self, registry: ToolRegistry):
        super().__init__()
        self.registry = registry

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("🧰 Herramientas cargadas", classes="title")
            yield DataTable(id="tools")

    def on_mount(self) -> None:
        table = self.query_one("#tools", DataTable)
        table.add_columns("Tool", "Estado", "Seguridad", "Descripción")
        for name, tool in sorted(self.registry.tools.items()):
            active = self.registry.is_active(name)
            estado = "[green]activa[/]" if active else "[dim]inactiva[/]"
            seg = "[red]peligrosa[/]" if tool.dangerous else "[green]segura[/]"
            desc = (tool.description or "").split(".")[0][:60]
            table.add_row(name, estado, seg, desc)

    def action_close(self) -> None:
        self.dismiss(None)
