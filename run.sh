#!/usr/bin/env bash
# Lanzador de k3sctl en contenedor. Hace TODO el setup por ti:
#   - prepara ~/.k3sctl con los permisos del usuario del contenedor (uid 10001),
#   - copia el kubeconfig a un sitio legible por ese usuario,
#   - lee la API key de un fichero (no hace falta exportarla cada vez),
#   - usa sudo para docker automáticamente si tu usuario no está en el grupo docker.
#
# Uso:
#   ./run.sh build               # construir la imagen
#   ./run.sh                     # arrancar la TUI (equivale a ./run.sh run)
#   ./run.sh run --read-only     # arrancar pasando flags extra al agente
#
# Configuración (todo opcional, con defaults para vuestro entorno Gemini):
#   ~/.k3sctl.env                fichero con secretos/config, p.ej:
#                                  K3SCTL_API_KEY=AQ...tu-key...
#                                  # K3SCTL_MODEL=gemini-2.5-flash
#   KUBECONFIG_HOST=...          kubeconfig de origen (default: ~/.kube/config)
#   K3SCTL_IMAGE / K3SCTL_STATE  imagen y dir de estado
set -euo pipefail

IMAGE="${K3SCTL_IMAGE:-k3sctl:latest}"
STATE="${K3SCTL_STATE:-$HOME/.k3sctl}"
KUBECONFIG_SRC="${KUBECONFIG_HOST:-$HOME/.kube/config}"
ENV_FILE="${K3SCTL_ENV_FILE:-$HOME/.k3sctl.env}"   # FUERA de STATE (legible por ti)
APP_UID=10001        # uid del usuario 'app' dentro de la imagen
APP_GID=10001

# Defaults de backend (Gemini AI Studio); overridables por env o por el env-file.
K3SCTL_BASE_URL="${K3SCTL_BASE_URL:-https://generativelanguage.googleapis.com/v1beta/openai/}"
K3SCTL_MODEL="${K3SCTL_MODEL:-gemini-2.5-flash}"

# ¿hace falta sudo para docker?
SUDO=""
if ! docker info >/dev/null 2>&1; then SUDO="sudo"; fi

cmd="${1:-run}"; shift || true

case "$cmd" in
  build)
    $SUDO docker build -t "$IMAGE" "$@" .
    ;;

  run)
    # Cargar secretos/config del env-file si existe.
    if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
    : "${K3SCTL_API_KEY:=${GEMINI_API_KEY:-}}"
    if [ -z "${K3SCTL_API_KEY:-}" ]; then
      echo "AVISO: K3SCTL_API_KEY vacío. Crea $ENV_FILE con 'K3SCTL_API_KEY=...'" >&2
      echo "       (con Ollama local no hace falta key)." >&2
    fi

    # Estado persistente, propiedad del uid del contenedor para evitar Permission denied.
    $SUDO mkdir -p "$STATE/sessions"
    $SUDO chown -R "$APP_UID:$APP_GID" "$STATE"

    # Copiar el kubeconfig a un sitio legible por el uid 10001.
    if [ -f "$KUBECONFIG_SRC" ]; then
      $SUDO cp "$KUBECONFIG_SRC" "$STATE/kubeconfig"
      $SUDO chown "$APP_UID:$APP_GID" "$STATE/kubeconfig"
      $SUDO chmod 600 "$STATE/kubeconfig"
    else
      echo "AVISO: no se encontró kubeconfig en $KUBECONFIG_SRC" >&2
    fi

    exec $SUDO docker run -it --rm \
      --network host \
      -v "$STATE:/home/app/.k3sctl" \
      -e K3SCTL_API_KEY="${K3SCTL_API_KEY:-}" \
      -e K3SCTL_BASE_URL="$K3SCTL_BASE_URL" \
      -e K3SCTL_MODEL="$K3SCTL_MODEL" \
      "$IMAGE" \
      --kubeconfig=/home/app/.k3sctl/kubeconfig --insecure-skip-tls-verify "$@"
    ;;

  *)
    echo "Uso: $0 {build|run} [flags-extra-del-agente...]" >&2
    exit 1
    ;;
esac
