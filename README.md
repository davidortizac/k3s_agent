# k3sctl

Agente conversacional para administrar clusters **k3s**, con **TUI estilo Claude
Code** (Textual), herramientas enchufables y un modelo de seguridad conservador
(confirmación para todo lo que modifique estado). Habla con cualquier LLM a través
de un endpoint **compatible con la API de OpenAI** (Ollama local, Google AI Studio /
Gemini, OpenAI).

> Reescritura del prototipo CLI/REPL original a una TUI contenedorizada. Conserva
> el bucle agéntico, la clasificación read/mutating, la memoria persistente, el
> histórico y la compactación de contexto; añade UI rica, plugins de herramientas y
> visores de memoria/histórico.

## Características

- **TUI** con stream de conversación (Markdown), tarjetas de tool-call colapsables
  con estado, barra de estado (modelo, modo, contexto, namespace, tokens, notas) y
  caja de entrada con historial.
- **Confirmación inline** (modal `y`/`n`) para toda operación que modifica el
  cluster. `--read-only` bloquea cualquier modificación.
- **Herramientas enchufables** auto-descubiertas en `k3sctl/tools/`:
  `run_kubectl`, `remember`, `run_helm`, `file_read`, y `shell` (desactivada por
  defecto; si se activa, todo es `mutating`).
- **Memoria persistente** (`~/.k3sctl/memory.json`) reinyectada en el system prompt,
  con visor para añadir/editar/borrar/buscar.
- **Histórico** append-only por sesión (`~/.k3sctl/sessions/*.jsonl`) con visor de
  auditoría legible y filtros.
- **Compactación de contexto** por bloques completos (turno de usuario + su cadena
  de tool-calls), preservando system + memoria + últimos N turnos.
- **Diagnóstico local** sin LLM (`/diag`): nodos NotReady y pods con problemas.
- **Multi-proveedor** vía flags/env; cambio de modelo en caliente con `/model`.

## Requisitos del backend LLM

- Camino principal: **OpenAI-compat**. Usa **Gemini 2.x** (`gemini-2.5-flash`,
  `gemini-2.0-flash-lite`). **Gemini 3.x NO** funciona por la capa OpenAI-compat
  para tool-calling multi-turno (`Function call is missing a thought_signature`);
  soportarlo exigiría el SDK nativo `google-genai` (extra opcional `gemini-native`,
  no implementado por defecto).
- Ollama local: `--base-url http://localhost:11434/v1`. Ajusta `--context-budget`
  por debajo del `num_ctx` real del modelo.

## Instalación local (desarrollo)

```bash
pip install -e ".[dev]"
k3sctl --help
python -m pytest -q          # 47 tests, sin red
```

Necesitas `kubectl` en el PATH (y `helm` si usas esa tool).

## Uso

```bash
# Ollama local (por defecto)
k3sctl --model qwen2.5:7b

# Gemini 2.5 Flash (AI Studio, OpenAI-compat)
export K3SCTL_API_KEY="<tu-api-key>"
k3sctl \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-2.5-flash \
  --context k3s-ha --namespace default

# Solo lectura (auditoría segura)
k3sctl --read-only
```

### Comandos dentro de la TUI

`/diag` · `/memory` · `/history` · `/tools` · `/model <id>` · `/readonly` ·
`/clear` · `/help` · `/quit`. Paleta de comandos con **Ctrl+P**. Historial de
entrada con flechas ↑/↓.

### Flags principales

| Flag | Env | Default |
|------|-----|---------|
| `--base-url` | `K3SCTL_BASE_URL` | `http://localhost:11434/v1` |
| `--model` | `K3SCTL_MODEL` | `qwen2.5:7b` |
| `--api-key` | `K3SCTL_API_KEY` | `ollama` |
| `--kubeconfig` | `KUBECONFIG` | — |
| `--context CTX` (repetible) | `K3SCTL_CONTEXTS` | — |
| `--namespace` | `K3SCTL_NAMESPACE` | `default` |
| `--read-only` | — | off |
| `--enable/--disable TOOL` | — | — |
| `--context-budget` | — | `8000` |
| `--keep-turns` | — | `6` |
| `--insecure-skip-tls-verify` | — | off |

El estado persistente vive en `~/.k3sctl` (override con `K3SCTL_HOME`).

## Contenedor

```bash
./run.sh build

K3SCTL_API_KEY="$GEMINI_API_KEY" ./run.sh run
# equivale a:
docker run -it --rm \
  --network host \
  -v "$HOME/.kube/config:/home/app/.kube/config:ro" \
  -v "$HOME/.k3sctl:/home/app/.k3sctl" \
  -e K3SCTL_API_KEY="$GEMINI_API_KEY" \
  -e K3SCTL_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/" \
  -e K3SCTL_MODEL="gemini-2.5-flash" \
  k3sctl:latest --kubeconfig=/home/app/.kube/config --insecure-skip-tls-verify
```

Notas de contenedorización:

- **TTY**: la TUI exige `docker run -it`. Con compose: `stdin_open: true` + `tty: true`.
- **Usuario no-root** (`uid 10001`); secretos por entorno, nunca horneados.
- **Volúmenes**: kubeconfig en `:ro`; `~/.k3sctl` en rw para persistir memoria/sesiones.
- **Red**: el contenedor debe alcanzar el API server (`10.1.110.11:6443`) y el LLM.
  Si el API server solo es accesible desde el host, usa `--network host`.
- **kubeconfig de k3s** apunta a `127.0.0.1`/`localhost`: reescribe `server:` al IP
  real del control-plane antes de montarlo (o usa un kubeconfig ya corregido). El
  certificado autofirmado puede requerir `--insecure-skip-tls-verify`.
- Pasa flags al agente como argumentos tras la imagen (`ENTRYPOINT k3sctl` + `CMD`).

## Arquitectura

```
k3sctl/
  app.py        TUI Textual; worker-thread para el motor; UIHooks (thread-safe)
  config.py     flags + env + defaults
  engine.py     bucle agéntico OpenAI-compat (síncrono, UI-agnóstico vía EngineHooks)
  context.py    estimación de tokens + compactación por bloques
  safety.py     clasificación read/mutating + allowlists (sin deps, testeada)
  memory.py     notas persistentes (escritura atómica + lock)
  history.py    JSONL append-only + lectores para el visor
  diagnose.py   diagnóstico local sin LLM
  prompts.py    system prompt (conectividad vs permisos, causas transitorias…)
  tools/        Tool base + registro auto-descubierto + kubectl/remember/helm/file_read/shell
  ui/           conversation, statusbar, confirm, memory_view, history_view, tools_view
tests/          test_safety, test_context, test_tools
```

### Seguridad

- Ninguna operación `mutating` sin confirmación explícita (o bloqueo en `--read-only`).
- `kubectl`/`shell`/`helm` se ejecutan vía `subprocess` con `shell=False` (sin
  expansión de shell). Contextos validados contra allowlist.
- JSON de argumentos inválido del modelo no crashea: se devuelve el error al LLM.
- Límite de pasos por turno (`--max-steps`). Sin telemetría; todo el estado en local.

## Nota de versiones

Verificado en 2026-06 contra PyPI: `textual 8.2.7`, `openai 2.43.0`, `rich 15.0.0`.
Las versiones de `kubectl`/`helm` se fijan como `ARG` en el `Dockerfile`; consulta
modelos disponibles de Gemini con `GET /v1beta/openai/models` antes de fijar uno.
```
