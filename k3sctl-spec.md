# Especificación: agente k3sctl con TUI dinámica (estilo Claude Code), contenedorizado

> Documento de encargo para una herramienta de codificación agéntica (Antigravity).
> Construye una aplicación nueva tomando como base un prototipo CLI ya funcional
> (descrito abajo). Respeta los requisitos de seguridad y las lecciones aprendidas.

---

## 1. Objetivo

Reescribir un agente conversacional de administración de Kubernetes (k3s) que hoy
es una CLI tipo REPL, convirtiéndolo en una **aplicación de terminal interactiva
(TUI) con experiencia similar a Claude Code**, empaquetada en un **contenedor
Docker**. Debe soportar **múltiples tipos de herramientas cargables** (no solo
kubectl) y ofrecer **visores integrados de la memoria persistente y del histórico
de sesiones**.

El agente habla con un LLM a través de un endpoint **compatible con la API de
OpenAI** (funciona con Ollama local, Google AI Studio / Gemini y OpenAI), y ejecuta
herramientas localmente con un modelo de seguridad conservador (confirmación para
todo lo que modifique estado).

---

## 2. Contexto: el prototipo actual que ya funciona

Existe un script `k3sctl.py` (~500 líneas, Python, dependencia única `openai`) ya
validado de extremo a extremo contra un cluster k3s HA real. Su comportamiento
actual, que debe **preservarse y mejorarse**:

- **Bucle agéntico** con *function calling*: el modelo propone comandos, el
  programa los ejecuta y devuelve la salida, encadenando hasta resolver.
- **Herramienta `run_kubectl(args, reason, context?)`**: ejecuta `kubectl` vía
  `subprocess` (lista de args, nunca `shell=True`).
- **Clasificación de comandos** en lectura vs. modificación. Verbos de lectura
  (`get`, `describe`, `logs`, `top`, `events`...) se ejecutan libres; los que
  modifican (`apply`, `delete`, `scale`, `drain`, `patch`...) **piden confirmación
  y/N** mostrando el comando exacto. Verbo desconocido = tratado como peligroso.
  Subcomandos ambiguos (`rollout status` vs `rollout restart`) se resuelven por el
  segundo token.
- **Modo `--read-only`** que bloquea por completo cualquier modificación.
- **Inyección automática** de `--kubeconfig`, `--context` y namespace por defecto.
- **Multi-contexto**: acepta varios contextos; el modelo elige contra cuál ejecutar
  vía un parámetro validado contra una allowlist.
- **Herramienta `remember(note)`** + memoria persistente en `~/.k3sctl/memory.json`
  (`{"notes": [{"t": iso, "note": str}]}`, tope 60 notas). Se reinyecta en el system
  prompt al arrancar.
- **Compactación automática de contexto**: estima tokens (~4 chars/token) y, al
  superar un presupuesto, recorta los intercambios más antiguos por bloques
  completos (un turno de usuario con toda su cadena de tool calls), preservando
  system prompt + memoria + últimos N turnos. Crítico para `num_ctx` chico de Ollama.
- **Histórico** append-only en `~/.k3sctl/sessions/session-<ts>.jsonl` (una línea
  por evento: user, assistant, command, blocked, cancelled, remember, diagnose).
- **Diagnóstico rápido local** (sin LLM): nodos NotReady, pods con problemas
  (estado != Running/Completed, READY incompleto, o ≥5 reinicios) y advertencias.
- Comandos REPL: `:diag`, `:memory`, `:remember <texto>`, `:forget`, `salir`.

### Entorno real donde corre (datos reales)

- Corre en una VM Ubuntu 24.04 (`k3s-admin-01`) que actúa de *jump host* dentro de
  la red del cluster.
- Cluster: **k3s v1.35.5+k3s1 HA**, 3 control-planes (`10.1.110.11-13`, etcd
  embebido) + 4 workers. Kubeconfig apunta directo a `https://10.1.110.11:6443`
  (no hay VIP de API server todavía → punto único de fallo conocido).
- Workers con taints/labels por ambiente: `env=dev` (sin taint), `env=test` +
  `dedicated=test:NoSchedule`, `env=qa` + `dedicated=qa:NoSchedule`.
- Stack: MetalLB (pool `10.1.110.50-62`, L2 VLAN 110), Ingress NGINX (entrada
  `10.1.110.50`), cert-manager (issuer autofirmado `selfsigned-gamma`), Longhorn
  (StorageClass por defecto), Argo CD, Prometheus/Grafana.
- LLM en uso: **Gemini 2.5 Flash** vía endpoint OpenAI-compat de Google AI Studio.

---

## 3. Lecciones aprendidas (NO repetir estos errores)

1. **Gemini 3.x NO funciona por la capa OpenAI-compat para herramientas
   multi-turno**: devuelve `Function call is missing a thought_signature`. Usar
   **Gemini 2.x** (`gemini-2.5-flash`, `gemini-2.0-flash-lite`) que no requiere
   `thought_signature`. Si en el futuro se quiere soportar 3.x, hay que migrar al
   SDK nativo `google-genai` y reenviar el `thought_signature` — documentarlo como
   backend opcional, no romper el camino OpenAI-compat.
2. **Modelos pequeños saltan a conclusiones**: tienden a confundir errores de
   conectividad (`got 0`) con errores de permisos (403). El system prompt debe
   instruir explícitamente distinguir ambos y NO proponer cambios hasta descartar
   causas transitorias (reinicios de arranque, etc.).
3. **Ubuntu/Debian moderno** bloquea `pip install` global (PEP 668). En contenedor,
   usar imagen base `python:3.12-slim` (sin esa restricción) o un venv en la imagen.
4. **kubeconfig de k3s** apunta a `127.0.0.1`; hay que reescribir el `server:`.
   Certificado autofirmado puede requerir `--insecure-skip-tls-verify` o `--tls-san`.
5. La confirmación y/N y la TUI requieren **TTY**: el contenedor debe correr con
   `-it` y la TUI debe manejar bien stdin interactivo.

---

## 4. Requisitos de la nueva aplicación

### 4.1. Interfaz TUI estilo Claude Code

Stack recomendado: **Python + [Textual](https://textual.textualize.io/)** (framework
TUI moderno, mismo autor que Rich). Es lo más cercano a una experiencia tipo Claude
Code en terminal. (Alternativa válida: Go + Bubble Tea, pero el prototipo es Python;
preferir Textual para reutilizar la lógica existente.)

La TUI debe ofrecer:

- **Stream de conversación** con scrollback: mensajes del usuario, texto del
  asistente renderizado en Markdown, y **tarjetas de tool-call** que muestren el
  comando, su estado (pendiente / ejecutando / ok / error / cancelado) y la salida
  colapsable.
- **Indicador de "pensando"** / spinner mientras el modelo responde, idealmente con
  *streaming* token a token de la respuesta del asistente.
- **Caja de entrada** persistente abajo, multilínea, con historial de comandos
  (flechas arriba/abajo).
- **Confirmación inline** para comandos que modifican: en vez de un `input()` crudo,
  un diálogo/modal con el comando resaltado y botones/teclas `y/n`. NUNCA ejecutar
  una modificación sin confirmación explícita.
- **Barra de estado** mostrando: backend/modelo activo, modo (read-only / conservador),
  contexto(s), namespace, uso de contexto aproximado (`~N/budget tokens`) y nº de
  notas en memoria.
- **Slash commands / atajos**: `/diag`, `/memory`, `/history`, `/tools`,
  `/model <id>`, `/readonly`, `/clear`, `/help`, `/quit`. Equivalentes a los `:`
  actuales.
- **Paleta de comandos** (Ctrl+P o similar) listando acciones y slash commands.
- Manejo correcto de redimensionado, colores con degradación si no hay TTY/colores.

### 4.2. Sistema de herramientas enchufables (multi-tool)

Generalizar más allá de kubectl con una **arquitectura de plugins**:

- Definir una clase/interfaz base `Tool` con: `name`, `description`,
  `json_schema` (para el `tools` de la API), `classify(call) -> "read"|"mutating"`,
  y `run(call) -> ToolResult`.
- **Auto-descubrimiento**: cargar todas las tools de un directorio `tools/`
  (entry points o escaneo de módulos). El conjunto de tools activas se inyecta en
  cada llamada al modelo.
- Tools a incluir de salida:
  - `kubectl` (porta la lógica actual: clasificación read/mutating, confirmación,
    inyección de context/namespace, allowlist).
  - `remember` (memoria persistente).
  - `shell` **opcional y desactivada por defecto** (ejecución de comandos de SO);
    si se habilita, TODO se trata como `mutating` (confirmación siempre).
  - `helm` (read: `list`, `status`, `get`; mutating: `install`, `upgrade`,
    `uninstall`, `rollback`).
  - `file_read` (lectura de manifiestos/YAML locales, solo lectura).
- Cada tool declara su propia política de seguridad; el motor central aplica
  confirmación según `classify()`. Un flag `--read-only` global desactiva todas las
  operaciones `mutating` de todas las tools.
- `/tools` muestra qué tools están cargadas y su estado (activa/inactiva, segura/peligrosa).
- Permitir activar/desactivar tools por flag o config (`--enable shell`,
  `--disable helm`).

### 4.3. Visor de memoria

- Pantalla/panel `/memory`: lista las notas con su timestamp, permite **añadir,
  editar y borrar** notas de forma segura (lectura/escritura de `memory.json` con
  bloqueo para no pisar escrituras del agente).
- Búsqueda/filtrado de notas.
- Indicar claramente que es conocimiento **estable** del cluster, separado del
  histórico de sesión.

### 4.4. Visor de histórico

- Pantalla/panel `/history`: lista las sesiones (`session-*.jsonl`) con fecha y
  resumen (nº de comandos, nº de modificaciones, modelo usado).
- Al abrir una sesión, render legible de la conversación y los comandos ejecutados
  (no JSON crudo), con filtros por tipo de evento (solo comandos, solo
  modificaciones, etc.).
- Solo lectura; no se reinyecta al contexto del modelo (es auditoría).

### 4.5. Multi-proveedor (preservar)

- Config por flags y/o variables de entorno: `--base-url`, `--model`, `--api-key`
  (y `K3SCTL_BASE_URL`, `K3SCTL_MODEL`, `K3SCTL_API_KEY`).
- Por defecto, Ollama local (`http://localhost:11434/v1`). Documentar también el
  endpoint de Gemini (`https://generativelanguage.googleapis.com/v1beta/openai/`)
  y OpenAI.
- `--context-budget` y `--keep-turns` para la compactación. Validar que el budget
  quede por debajo del `num_ctx` real cuando se use Ollama.
- `/model <id>` para cambiar de modelo en caliente.

---

## 5. Contenedorización

- **Imagen base**: `python:3.12-slim`.
- Instalar en la imagen: dependencias Python (`openai`, `textual`, `rich`, y lo que
  use el plugin system) y el binario **`kubectl`** (descargar la versión estable de
  `dl.k8s.io`). Opcional: `helm`.
- **Usuario no-root** dentro del contenedor.
- **Volúmenes** (no hornear secretos ni configs en la imagen):
  - kubeconfig montado en solo-lectura (p. ej. `-v ~/.kube/config:/home/app/.kube/config:ro`).
  - directorio de estado persistente `~/.k3sctl` (memoria + sesiones) montado
    read-write para que sobreviva entre ejecuciones.
- **Secretos por entorno**: la API key del LLM vía variable de entorno o secreto de
  Docker, nunca en la imagen.
- **Red**: el contenedor necesita alcanzar el API server del cluster
  (`10.1.110.11:6443`) y el endpoint del LLM. Documentar `--network host` si hiciera
  falta para llegar a la red del cluster, o las reglas pertinentes.
- **TTY**: la TUI exige `docker run -it`. Documentarlo.
- Entregar `Dockerfile`, `.dockerignore`, `docker-compose.yml` (con los montajes y
  env vars), y un `Makefile`/script `run.sh` con los comandos de build y run.
- Documentar cómo pasar flags al agente dentro del contenedor (ENTRYPOINT + CMD).

Ejemplo del run esperado (orientativo, ajústalo):

```bash
docker run -it --rm \
  --network host \
  -v "$HOME/.kube/config:/home/app/.kube/config:ro" \
  -v "$HOME/.k3sctl:/home/app/.k3sctl" \
  -e K3SCTL_API_KEY="$GEMINI_API_KEY" \
  -e K3SCTL_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/" \
  -e K3SCTL_MODEL="gemini-2.5-flash" \
  k3sctl:latest
```

---

## 6. Estructura de proyecto sugerida

```
k3sctl/
  pyproject.toml
  Dockerfile
  .dockerignore
  docker-compose.yml
  run.sh
  README.md
  k3sctl/
    __init__.py
    app.py            # entrypoint TUI (Textual App)
    config.py         # flags + env + defaults
    engine.py         # bucle agéntico, llamada al LLM, streaming
    context.py        # estimación de tokens + compactación
    memory.py         # Memory (persistente)
    history.py        # History (JSONL append-only)
    safety.py         # clasificación read/mutating, allowlists
    tools/
      base.py         # clase Tool + registry/descubrimiento
      kubectl_tool.py
      remember_tool.py
      helm_tool.py
      file_read_tool.py
      shell_tool.py   # desactivada por defecto
    ui/
      conversation.py # widget de stream + tarjetas de tool-call
      confirm.py      # modal de confirmación y/N
      memory_view.py
      history_view.py
      statusbar.py
  tests/
    test_safety.py    # clasificación de verbos
    test_context.py   # compactación
    test_tools.py
```

---

## 7. Requisitos no funcionales

- **Seguridad primero**: ninguna operación `mutating` sin confirmación explícita;
  nunca `shell=True`; tools peligrosas desactivadas por defecto; `--read-only`
  manda sobre todo.
- **Sin dependencia de un solo proveedor**: todo a través de la interfaz
  OpenAI-compat; el SDK nativo de Google solo como backend opcional documentado.
- **Robustez con modelos flojos**: tolerar JSON inválido en argumentos de tool
  (capturar y devolver error al modelo, no crashear), límite de pasos por turno.
- **Tests** unitarios de la lógica de seguridad y de la compactación (sin red).
- **Sin telemetría**; todo el estado en local (`~/.k3sctl`).

---

## 8. System prompt (mejorar respecto al actual)

Mantener el tono experto en k3s y añadir:

- Distinguir explícitamente **errores de conectividad** (timeouts, `got 0`, i/o
  timeout) de **errores de permisos** (403/Forbidden), y no confundirlos.
- No proponer cambios hasta **descartar causas transitorias** (reinicios de
  arranque, pods que ya se estabilizaron, eventos antiguos).
- Preferir diagnóstico read-only exhaustivo antes de cualquier `mutating`.
- Indicar siempre QUÉ se cambia y POR QUÉ antes de una modificación.
- Tener en cuenta la memoria persistente (taints por ambiente, Longhorn por
  defecto, `10.1.110.50` es ingress y no API server, cert autofirmado esperado).

---

## 9. Criterios de aceptación

1. `docker build` produce una imagen que arranca la TUI con `docker run -it`.
2. La TUI muestra stream del asistente, tarjetas de tool-call y barra de estado.
3. Una pregunta de diagnóstico encadena varias tools de lectura y resume hallazgos.
4. Una orden de modificación (`escala el deployment X a N`) muestra un **modal de
   confirmación**; al aceptar, ejecuta; al rechazar, cancela. En `--read-only`, se
   bloquea.
5. `/memory` lista, añade y borra notas, persistiendo en `memory.json`.
6. `/history` lista sesiones y muestra una sesión pasada de forma legible.
7. `/tools` lista las tools cargadas; `shell` aparece desactivada por defecto.
8. Cambiar de modelo con `/model gemini-2.5-flash` funciona en caliente.
9. La compactación recorta intercambios antiguos al superar el budget, sin romper
   la estructura de tool calls.
10. Funciona contra Gemini 2.5 Flash (OpenAI-compat) y contra Ollama local.

---

## 10. Nota de versiones

Las versiones exactas de librerías (Textual, openai SDK), los identificadores de
modelos de Gemini y detalles de las APIs pueden haber cambiado. Antes de fijar
dependencias, **verifica las versiones actuales** y los modelos disponibles
(`GET /v1beta/openai/models`). Prioriza un modelo de la familia **Gemini 2.x** para
el camino OpenAI-compat por el tema del `thought_signature`.
```

