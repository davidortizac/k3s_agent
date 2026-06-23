"""Tests de la TUI que ejercitan el renderizado de tarjetas de tool-call.

Regresión: ToolCard heredaba un nombre (`_title`) que colisionaba con un atributo
interno de `Collapsible` de Textual, provocando un crash al pintar la primera
tool-call real. Estos tests montan widgets de verdad vía run_test().
"""

import asyncio
import pathlib
import tempfile

from k3sctl.config import Config
from k3sctl.ui.conversation import ConversationView, ToolCard


def _cfg() -> Config:
    return Config(home=pathlib.Path(tempfile.mkdtemp()))


def test_tool_card_lifecycle_read_and_mutating():
    async def run():
        # App mínima que solo monta una ConversationView.
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ConversationView()

        app = _App()
        async with app.run_test() as pilot:
            conv = app.query_one(ConversationView)

            # Tool-call de lectura: start -> running -> ok.
            conv.add_tool_card("c1", "kubectl get nodes -o wide", "read", "ver nodos")
            await pilot.pause()
            card1 = conv._tool_cards["c1"]
            assert isinstance(card1, ToolCard)
            assert card1._status == "running"
            conv.update_tool_result("c1", True, "NAME STATUS\nnode1 Ready")
            await pilot.pause()
            assert card1._status == "ok"

            # Tool-call de modificación que falla: se marca error y se expande.
            conv.add_tool_card("c2", "kubectl delete pod x", "mutating", "borrar")
            await pilot.pause()
            conv.update_tool_result("c2", False, "Error from server")
            await pilot.pause()
            card2 = conv._tool_cards["c2"]
            assert card2._status == "error"
            assert card2.collapsed is False  # los errores se despliegan solos

            # Bloqueo (read-only) sobre una tercera.
            conv.add_tool_card("c3", "kubectl scale deploy/api --replicas=3", "mutating", "")
            await pilot.pause()
            conv.mark_tool_blocked("c3", "Modo solo-lectura: operación bloqueada.")
            await pilot.pause()
            assert conv._tool_cards["c3"]._status == "blocked"

    asyncio.run(run())


def test_conversation_streaming_and_user_message():
    async def run():
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ConversationView()

        app = _App()
        async with app.run_test() as pilot:
            conv = app.query_one(ConversationView)
            conv.add_user("¿estado del cluster?")
            await pilot.pause()
            conv.add_assistant_delta("Voy ")
            conv.add_assistant_delta("a mirar.")
            await pilot.pause()
            conv.add_assistant_message("Voy a mirar.")  # cierra el bloque
            await pilot.pause()
            # No debe lanzar; el buffer acumuló el streaming.
            assert conv._current_assistant is None

    asyncio.run(run())
