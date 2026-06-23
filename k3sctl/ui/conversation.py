"""Stream de conversación: mensajes de usuario/asistente y tarjetas de tool-call.

Se usa Rich Markdown dentro de un `Static` (update síncrono) en lugar del widget
Markdown (update asíncrono) para poder actualizar cómodamente desde callbacks que
llegan vía `call_from_thread`.
"""

from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Static

# Estados de una tool-call y su decoración.
STATUS_ICON = {
    "pending": ("⏳", "yellow"),
    "running": ("▶", "cyan"),
    "ok": ("✓", "green"),
    "error": ("✗", "red"),
    "blocked": ("🛑", "red"),
    "cancelled": ("⊘", "yellow"),
}


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage { color: $text; margin: 1 0 0 0; padding: 0 1; }
    """

    def __init__(self, text: str):
        super().__init__(Text.assemble(("❯ ", "bold cyan"), (text, "bold")))


class AssistantMessage(Static):
    DEFAULT_CSS = """
    AssistantMessage { margin: 0 0 0 0; padding: 0 1; }
    """

    def __init__(self):
        super().__init__("")
        self._buffer = ""

    def append(self, text: str) -> None:
        self._buffer += text
        self.update(RichMarkdown(self._buffer))

    def set_text(self, text: str) -> None:
        self._buffer = text
        self.update(RichMarkdown(self._buffer))


class ToolCard(Collapsible):
    """Tarjeta de tool-call: título con estado + comando, cuerpo con la salida."""

    DEFAULT_CSS = """
    ToolCard { margin: 1 1; border: round $panel; }
    ToolCard .tool-output { padding: 0 1; color: $text-muted; }
    """

    def __init__(self, call_id: str, display: str, classification: str, reason: str):
        self.call_id = call_id
        self.command_display = display
        self.classification = classification
        self.reason = reason
        self._status = "pending"
        self._output_widget = Static("(pendiente)", classes="tool-output")
        # OJO: `Collapsible` ya define un atributo de instancia `_title` (el widget
        # del título), así que NO podemos usar ese nombre para nuestro método.
        super().__init__(self._output_widget, title=self._title_markup(), collapsed=True)

    def _title_markup(self) -> str:
        icon, color = STATUS_ICON.get(self._status, ("?", "white"))
        tag = "MOD" if self.classification == "mutating" else "lec"
        return f"[{color}]{icon}[/] [{tag}] {self.command_display}"

    def set_status(self, status: str) -> None:
        self._status = status
        self.title = self._title_markup()

    def set_output(self, text: str, expand: bool = False) -> None:
        self._output_widget.update(text or "(sin salida)")
        if expand:
            self.collapsed = False


class ConversationView(VerticalScroll):
    """Contenedor con scrollback de todos los mensajes."""

    DEFAULT_CSS = """
    ConversationView { padding: 0 1; }
    """

    def __init__(self):
        super().__init__()
        self._tool_cards: dict[str, ToolCard] = {}
        self._current_assistant: AssistantMessage | None = None

    def compose(self) -> ComposeResult:
        return []

    # -- mensajes -----------------------------------------------------------
    def add_user(self, text: str) -> None:
        self.mount(UserMessage(text))
        self._current_assistant = None
        self.scroll_end(animate=False)

    def _ensure_assistant(self) -> AssistantMessage:
        if self._current_assistant is None:
            self._current_assistant = AssistantMessage()
            self.mount(self._current_assistant)
        return self._current_assistant

    def add_assistant_delta(self, text: str) -> None:
        self._ensure_assistant().append(text)
        self.scroll_end(animate=False)

    def add_assistant_message(self, text: str) -> None:
        # Si no hubo streaming previo, fija el texto completo.
        msg = self._ensure_assistant()
        if not msg._buffer:
            msg.set_text(text)
        self._current_assistant = None  # cierra el bloque del asistente
        self.scroll_end(animate=False)

    def add_notice(self, text: str, style: str = "yellow") -> None:
        self.mount(Static(Text(text, style=style), classes="notice"))
        self.scroll_end(animate=False)

    # -- tool cards ---------------------------------------------------------
    def add_tool_card(self, call_id: str, display: str, classification: str, reason: str) -> None:
        # Una tool-call cierra el bloque de texto del asistente en curso.
        self._current_assistant = None
        card = ToolCard(call_id, display, classification, reason)
        self._tool_cards[call_id] = card
        self.mount(card)
        card.set_status("running")
        self.scroll_end(animate=False)

    def update_tool_result(self, call_id: str, ok: bool, output: str) -> None:
        card = self._tool_cards.get(call_id)
        if card is None:
            return
        card.set_status("ok" if ok else "error")
        card.set_output(output, expand=not ok)
        self.scroll_end(animate=False)

    def mark_tool_blocked(self, call_id: str, reason: str) -> None:
        card = self._tool_cards.get(call_id)
        if card is None:
            return
        card.set_status("blocked" if "solo-lectura" in reason.lower() else "cancelled")
        card.set_output(reason, expand=True)
        self.scroll_end(animate=False)
