"""Modal de confirmación y/N para operaciones mutating."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Devuelve True (ejecutar) o False (cancelar)."""

    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical {
        width: 80%; max-width: 100; height: auto; padding: 1 2;
        border: thick $warning; background: $surface;
    }
    ConfirmModal .title { text-style: bold; color: $warning; margin-bottom: 1; }
    ConfirmModal .cmd { color: $text; background: $panel; padding: 1; margin: 1 0; }
    ConfirmModal .reason { color: $text-muted; margin-bottom: 1; }
    ConfirmModal #buttons { height: auto; align: right middle; }
    ConfirmModal Button { margin-left: 2; }
    """

    BINDINGS = [
        ("y", "approve", "Ejecutar"),
        ("n", "reject", "Cancelar"),
        ("escape", "reject", "Cancelar"),
    ]

    def __init__(self, tool: str, display: str, reason: str):
        super().__init__()
        self._tool = tool
        self._display = display
        self._reason = reason

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("⚠ Confirmar operación que MODIFICA estado", classes="title")
            yield Static(Text(self._display, style="bold"), classes="cmd")
            if self._reason:
                yield Static(f"Motivo del modelo: {self._reason}", classes="reason")
            yield Static("¿Ejecutar?  [y] sí   [n] no", classes="reason")
            with Vertical(id="buttons"):
                yield Button("Ejecutar (y)", variant="error", id="approve")
                yield Button("Cancelar (n)", variant="primary", id="reject")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)
