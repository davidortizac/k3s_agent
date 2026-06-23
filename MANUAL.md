# Manual de uso — k3sctl

Guía práctica para operar el agente conversacional **k3sctl**. Para instalación
detallada y arquitectura, ver [README.md](README.md). Para desplegarlo en el jump
host, ver [DEPLOY.md](DEPLOY.md) (si existe).

---

## Índice

1. [Qué es y cómo piensa](#1-qué-es-y-cómo-piensa)
2. [Arranque rápido](#2-arranque-rápido)
3. [La interfaz (TUI)](#3-la-interfaz-tui)
4. [Conversar con el agente](#4-conversar-con-el-agente)
5. [El modelo de seguridad](#5-el-modelo-de-seguridad)
6. [Slash commands](#6-slash-commands)
7. [Visor de memoria](#7-visor-de-memoria)
8. [Visor de histórico](#8-visor-de-histórico)
9. [Herramientas](#9-herramientas)
10. [Elegir backend y modelo](#10-elegir-backend-y-modelo)
11. [Flags y variables de entorno](#11-flags-y-variables-de-entorno)
12. [Recetas habituales](#12-recetas-habituales)
13. [Resolución de problemas](#13-resolución-de-problemas)

---

## 1. Qué es y cómo piensa

k3sctl es un asistente experto en k3s que **conversa contigo** y **ejecuta
herramientas** (kubectl, helm, lectura de ficheros…) para diagnosticar y operar el
cluster. No es un chatbot que solo habla: encadena comandos de lectura, analiza la
salida y te propone acciones.

Su forma de trabajar está guiada por el system prompt:

- **Diagnostica antes de actuar**: prefiere lectura exhaustiva antes de cualquier cambio.
- **Distingue conectividad de permisos**: un `timeout`/`got 0` (red) no es lo mismo
  que un `403/Forbidden` (autorización), y no los confunde.
- **Descarta causas transitorias** (arranques, reinicios recientes) antes de mutar.
- **Explica QUÉ cambia y POR QUÉ** antes de pedirte confirmación.

> Regla de oro: **toda operación que modifica el cluster requiere tu confirmación
> explícita** (o queda bloqueada en modo solo-lectura). El agente nunca muta a tus
> espaldas.

---

## 2. Arranque rápido

**Contra Ollama local** (sin API key):
```bash
k3sctl --model llama3.1:8b
```

**Contra Gemini 2.5 Flash** (OpenAI-compat de Google AI Studio):
```bash
export K3SCTL_API_KEY="<tu-api-key>"
k3sctl \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-2.5-flash \
  --context <tu-contexto> --insecure-skip-tls-verify
```

**Modo seguro para empezar** (no puede modificar nada):
```bash
k3sctl --read-only
```

**En contenedor**:
```bash
K3SCTL_API_KEY="$GEMINI_API_KEY" ./run.sh run
```

La TUI necesita un terminal interactivo (TTY). En Docker, siempre con `-it`.

---

## 3. La interfaz (TUI)

```
┌──────────────────────────────────────────────────────────────┐
│  ❯ ¿por qué el pod api está en CrashLoopBackOff?              │  ← tu mensaje
│                                                                │
│  Voy a revisar el estado y los logs del pod…                  │  ← asistente (Markdown)
│  ┌ ✓ [lec] kubectl get pod api -o wide ───────────────────┐  │  ← tarjeta de tool-call
│  │ (clic/Enter para desplegar la salida)                   │  │     (colapsable)
│  └─────────────────────────────────────────────────────────┘  │
│  ┌ ✓ [lec] kubectl logs api --tail=50 ─────────────────────┐  │
│  └─────────────────────────────────────────────────────────┘  │
│  El contenedor falla al conectar con Postgres (10.1.110.x)…   │
├────────────────────────────────────────────────────────────────┤
│ gemini-2.5-flash │ conservador │ ctx:k3s-ha │ ns:default │ ~3k/8k tok │ mem:7 │  ← barra de estado
├────────────────────────────────────────────────────────────────┤
│ Pregunta o instrucción…  (/help para comandos)                 │  ← caja de entrada
└────────────────────────────────────────────────────────────────┘
```

**Elementos:**

- **Stream de conversación** (arriba, con scroll): tus mensajes, el texto del
  asistente en Markdown y las **tarjetas de tool-call**.
- **Tarjetas de tool-call**: muestran un icono de estado, una etiqueta
  `[lec]`/`[MOD]` (lectura o modificación) y el comando exacto. Se **despliegan**
  para ver la salida (las que fallan se abren solas).
  - ⏳ pendiente · ▶ ejecutando · ✓ ok · ✗ error · 🛑 bloqueado · ⊘ cancelado
- **Barra de estado** (abajo): modelo · modo (conservador/READ-ONLY) · contexto ·
  namespace · uso de contexto `~usado/budget tokens` · nº de notas en memoria.
- **Caja de entrada**: multilínea; **↑/↓** recorre tu historial de comandos.

**Atajos de teclado:**

| Tecla | Acción |
|-------|--------|
| `Enter` | Enviar mensaje / comando |
| `↑` / `↓` | Historial de entrada |
| `Ctrl+P` | Paleta de comandos (busca acciones) |
| `Ctrl+L` | Limpiar conversación |
| `Ctrl+R` | Alternar modo solo-lectura |
| `Ctrl+C` | Salir |
| `Esc` | Cerrar un modal/visor |

---

## 4. Conversar con el agente

Escribe en lenguaje natural. Ejemplos:

- `dame un resumen de la salud del cluster`
- `¿qué pods están reiniciándose en kube-system?`
- `revisa por qué el ingress no responde en 10.1.110.50`
- `escala el deployment api a 4 réplicas` → **pedirá confirmación**

Mientras el modelo responde verás el texto aparecer en **streaming** y la entrada
se deshabilita con el texto "Pensando…". Cuando termina el turno, vuelve el foco a
la caja de entrada.

Un "turno" puede encadenar **varias herramientas** automáticamente (p. ej. `get
pods` → `describe` → `logs`) hasta que el agente tiene lo que necesita para
responder. Hay un tope de pasos por turno (`--max-steps`, 25 por defecto).

---

## 5. El modelo de seguridad

Es el corazón de k3sctl. Cada comando se clasifica como **lectura** o
**modificación**:

- **Lectura** (`get`, `describe`, `logs`, `top`, `events`, `rollout status`…):
  se ejecuta directamente, sin molestarte.
- **Modificación** (`apply`, `delete`, `scale`, `drain`, `patch`, `cordon`,
  `rollout restart`…): **abre un modal de confirmación**.
- **Verbo desconocido**: se trata como modificación (conservador).

### El modal de confirmación

Cuando el agente quiere modificar algo, se detiene y muestra:

```
        ⚠ Confirmar operación que MODIFICA estado
        ┌──────────────────────────────────────────┐
        │ kubectl scale deployment/api --replicas=4 │
        └──────────────────────────────────────────┘
        Motivo del modelo: aumentar capacidad ante carga
        ¿Ejecutar?  [y] sí   [n] no
```

- **`y`** → ejecuta el comando exacto que ves.
- **`n`** o **`Esc`** → cancela; el agente recibe "cancelado por el usuario" y
  continúa sin haber tocado nada.

### Modo solo-lectura

Con `--read-only` (o `Ctrl+R` / `/readonly` en caliente) **toda** modificación
queda **bloqueada** sin posibilidad de confirmar. Ideal para auditoría o para dar
acceso a alguien sin riesgo. La barra de estado lo muestra en rojo: `READ-ONLY`.

> El modo manda sobre todas las herramientas a la vez. No hay forma de saltárselo
> desde la conversación.

---

## 6. Slash commands

Escríbelos en la caja de entrada (o búscalos con `Ctrl+P`):

| Comando | Qué hace |
|---------|----------|
| `/help` | Muestra la ayuda con todos los comandos |
| `/diag` | **Diagnóstico local sin LLM**: nodos NotReady y pods con problemas |
| `/memory` | Abre el visor/editor de memoria persistente |
| `/history` | Abre el visor de sesiones pasadas (auditoría) |
| `/tools` | Lista las herramientas cargadas y su estado |
| `/model <id>` | Cambia el modelo **en caliente** (p. ej. `/model gemini-2.5-flash`) |
| `/readonly` | Activa/desactiva el modo solo-lectura |
| `/clear` | Limpia la conversación actual (resetea el contexto) |
| `/quit` | Salir |

`/model` sin argumento muestra el modelo actual.

---

## 7. Visor de memoria

`/memory` abre la **memoria persistente**: conocimiento **estable** del cluster que
sobrevive entre sesiones y se reinyecta en el system prompt al arrancar.

- **Añadir**: escribe en la caja inferior y pulsa Enter (o el botón "Añadir").
- **Borrar**: selecciona una nota y pulsa **`d`**.
- **Buscar/filtrar**: escribe el texto y pulsa **`Ctrl+F`** (o el botón "Buscar").
- **Cerrar**: `Esc`.

Cada nota lleva su timestamp. El tope es de 60 notas (se descartan las más antiguas).

**Qué SÍ recordar** (estable): "Longhorn es la StorageClass por defecto",
"10.1.110.50 es el Ingress, no el API server", "workers qa tienen taint
dedicated=qa:NoSchedule".
**Qué NO** (transitorio): "el pod X está caído ahora".

El agente también puede añadir notas él mismo con la herramienta `remember` (no
requiere confirmación, solo escribe en disco local).

---

## 8. Visor de histórico

`/history` abre el registro de **sesiones pasadas** (solo auditoría; **no** se
reinyecta al modelo).

- **Panel izquierdo**: lista de sesiones con fecha, nº de comandos y nº de
  modificaciones.
- **Panel derecho**: al seleccionar una sesión, render legible de la conversación y
  los comandos (no JSON crudo).
- **Filtros**: `c` solo comandos · `m` solo modificaciones · `a` todo.
- **Cerrar**: `Esc`.

Cada sesión se guarda en `~/.k3sctl/sessions/session-<fecha>.jsonl`, una línea por
evento (user, assistant, command, blocked, cancelled, remember, diagnose…).

---

## 9. Herramientas

`/tools` lista lo que el agente tiene disponible:

| Tool | Tipo | Por defecto | Notas |
|------|------|-------------|-------|
| `run_kubectl` | segura | activa | Lectura libre; modificación con confirmación |
| `remember` | segura | activa | Guarda notas en memoria |
| `run_helm` | segura | activa | Lectura: list/status/get; modificación: install/upgrade/uninstall/rollback |
| `file_read` | segura | activa | Lee manifiestos/YAML locales (solo lectura, máx 64KB) |
| `shell` | ⚠ peligrosa | **inactiva** | Comandos de SO; **todo** se trata como modificación |

**Activar/desactivar** tools al lanzar:
```bash
k3sctl --enable shell          # activar la shell (úsala con cuidado)
k3sctl --disable run_helm      # desactivar helm
```

La `shell` no usa expansión de shell (sin pipes ni `;`): ejecuta un único programa
con sus argumentos. Aun así, va **desactivada por defecto** por seguridad.

---

## 10. Elegir backend y modelo

k3sctl habla con cualquier endpoint **compatible con la API de OpenAI**.

| Backend | `--base-url` | Ejemplo de `--model` |
|---------|--------------|----------------------|
| Ollama (local) | `http://localhost:11434/v1` | `llama3.1:8b`, `qwen3.6:27b` |
| Gemini (AI Studio) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |

> **Importante**: usa **Gemini 2.x** (`gemini-2.5-flash`, `gemini-2.0-flash-lite`).
> **Gemini 3.x NO funciona** por la capa OpenAI-compat con herramientas multi-turno
> (error `Function call is missing a thought_signature`).

Cambia de modelo sin reiniciar con `/model <id>`.

**Ollama y el contexto**: ajusta `--context-budget` por debajo del `num_ctx` real
del modelo, o el agente recortará la conversación demasiado tarde. La barra de
estado muestra el uso aproximado (`~usado/budget tokens`); cuando se supera el
budget, k3sctl compacta automáticamente los turnos más antiguos (preservando el
system prompt, la memoria y los últimos turnos).

---

## 11. Flags y variables de entorno

| Flag | Variable de entorno | Default |
|------|--------------------|---------|
| `--base-url` | `K3SCTL_BASE_URL` | `http://localhost:11434/v1` |
| `--model` | `K3SCTL_MODEL` | `qwen2.5:7b` |
| `--api-key` | `K3SCTL_API_KEY` | `ollama` |
| `--kubeconfig` | `KUBECONFIG` | — |
| `--context CTX` (repetible) | `K3SCTL_CONTEXTS` (coma) | — |
| `--default-context` | — | primero de `--context` |
| `--namespace`, `-n` | `K3SCTL_NAMESPACE` | `default` |
| `--read-only` | — | desactivado |
| `--enable TOOL` / `--disable TOOL` | — | — |
| `--insecure-skip-tls-verify` | — | desactivado |
| `--context-budget` | — | `8000` |
| `--keep-turns` | — | `6` |
| `--max-steps` | — | `25` |
| (dir de estado) | `K3SCTL_HOME` | `~/.k3sctl` |

Precedencia: **flag** > **variable de entorno** > **default**.

Los contextos pasados con `--context` forman una **allowlist**: el agente solo puede
ejecutar contra esos contextos; cualquier otro se rechaza.

---

## 12. Recetas habituales

**Auditoría segura de un cluster ajeno:**
```bash
k3sctl --read-only --context cliente-prod --kubeconfig ./cliente.yaml
```

**Operación normal en tu HA con confirmaciones:**
```bash
k3sctl --context k3s-ha --context k3s-dev --namespace default \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-2.5-flash --insecure-skip-tls-verify
```

**Modelo local pequeño (contexto reducido):**
```bash
k3sctl --model granite4.1:3b --context-budget 4000 --keep-turns 4
```

**Empezar una sesión:**
1. `/diag` para una foto rápida del estado (sin gastar tokens).
2. Pregunta en lenguaje natural sobre lo que veas raro.
3. Deja que encadene lecturas; revisa las tarjetas de tool-call.
4. Si propone un cambio, lee el comando en el modal antes de pulsar `y`.

---

## 13. Resolución de problemas

| Síntoma | Causa probable / solución |
|---------|---------------------------|
| `kubectl no está instalado` | Instálalo en el PATH (o usa el contenedor, que lo incluye). |
| Errores de conexión al API server (`got 0`, timeout) | Red/jump host, no permisos. Verifica que alcanzas `10.1.110.11:6443`; usa `--network host` en Docker. |
| `x509`/certificado | Cert autofirmado de k3s: añade `--insecure-skip-tls-verify`. |
| `Function call is missing a thought_signature` | Estás usando Gemini 3.x. Cambia a `gemini-2.5-flash`. |
| `kubeconfig` apunta a `127.0.0.1` | Reescribe `server:` al IP del control-plane (ver DEPLOY/README). |
| La TUI se ve rota / sin color | Falta TTY. En Docker usa `docker run -it`. |
| El modelo "salta a conclusiones" | Modelos pequeños tienden a ello; usa uno mayor o recuérdale distinguir conectividad de permisos. |
| Contexto se llena muy rápido (Ollama) | Baja `--context-budget` por debajo del `num_ctx`, y/o `--keep-turns`. |
| Quiero que NO pueda tocar nada | `--read-only` (o `Ctrl+R` en caliente). |
| El agente pidió una tool desactivada | Actívala con `--enable <tool>` si procede. |

**Dónde mirar el estado**: todo vive en `~/.k3sctl/` (`memory.json` y
`sessions/`). No hay telemetría; nada sale de tu máquina salvo las llamadas al LLM
que tú configures.
