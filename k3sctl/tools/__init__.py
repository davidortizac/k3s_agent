"""Sistema de herramientas enchufables.

Cada módulo de este paquete que defina una subclase de `Tool` y exponga una
función `register() -> Tool` (o varias vía `register_all() -> list[Tool]`) es
auto-descubierto por `discover_tools()`.
"""
