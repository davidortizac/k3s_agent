"""k3sctl: agente conversacional para administrar clusters k3s.

Arquitectura:
  - config:   flags + variables de entorno + valores por defecto.
  - safety:   clasificación read/mutating y allowlists (sin dependencias).
  - tools/:   sistema de herramientas enchufables (kubectl, remember, helm, ...).
  - memory:   notas persistentes (~/.k3sctl/memory.json).
  - history:  histórico append-only de sesiones (~/.k3sctl/sessions/*.jsonl).
  - context:  estimación de tokens y compactación de la conversación.
  - engine:   bucle agéntico contra un endpoint OpenAI-compat (UI-agnóstico).
  - ui/, app: TUI Textual estilo Claude Code.
"""

__version__ = "0.1.0"
