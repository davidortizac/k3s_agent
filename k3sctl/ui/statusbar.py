"""Barra de estado inferior: backend/modelo, modo, contexto, namespace, tokens, notas."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """

    def update_status(self, info: dict) -> None:
        mode = "READ-ONLY" if info.get("read_only") else "conservador"
        mode_style = "bold red" if info.get("read_only") else "green"
        used = info.get("tokens_used", 0)
        budget = info.get("tokens_budget", 0)
        ratio = used / budget if budget else 0
        tok_style = "red" if ratio > 0.9 else ("yellow" if ratio > 0.7 else "dim")

        t = Text()
        t.append(f" {info.get('model', '?')} ", "bold cyan")
        t.append("│ ", "dim")
        t.append(mode, mode_style)
        t.append(" │ ctx:", "dim")
        t.append(str(info.get("context") or "default"))
        t.append(" │ ns:", "dim")
        t.append(str(info.get("namespace", "default")))
        t.append(" │ ", "dim")
        t.append(f"~{used}/{budget} tok", tok_style)
        t.append(" │ ", "dim")
        t.append(f"mem:{info.get('notes', 0)}", "dim")
        self.update(t)
