#!/usr/bin/env bash
# Build & run de k3sctl en contenedor. La TUI exige TTY (-it).
#
# Variables de entorno relevantes:
#   K3SCTL_API_KEY   API key del LLM (obligatoria salvo Ollama local).
#   K3SCTL_BASE_URL  endpoint OpenAI-compat (default: Gemini AI Studio).
#   K3SCTL_MODEL     modelo (default: gemini-2.5-flash).
#   KUBECONFIG_HOST  ruta al kubeconfig en el host (default: ~/.kube/config).
#   K3SCTL_STATE     dir de estado persistente (default: ~/.k3sctl).
#
# Uso:
#   ./run.sh build                 # construye la imagen
#   ./run.sh run [flags...]        # arranca la TUI (pasa flags extra al agente)
set -euo pipefail

IMAGE="k3sctl:latest"
KUBECONFIG_HOST="${KUBECONFIG_HOST:-$HOME/.kube/config}"
K3SCTL_STATE="${K3SCTL_STATE:-$HOME/.k3sctl}"
K3SCTL_BASE_URL="${K3SCTL_BASE_URL:-https://generativelanguage.googleapis.com/v1beta/openai/}"
K3SCTL_MODEL="${K3SCTL_MODEL:-gemini-2.5-flash}"

cmd="${1:-run}"; shift || true

case "$cmd" in
  build)
    docker build -t "$IMAGE" .
    ;;
  run)
    mkdir -p "$K3SCTL_STATE"
    docker run -it --rm \
      --network host \
      -v "$KUBECONFIG_HOST:/home/app/.kube/config:ro" \
      -v "$K3SCTL_STATE:/home/app/.k3sctl" \
      -e K3SCTL_API_KEY="${K3SCTL_API_KEY:-}" \
      -e K3SCTL_BASE_URL="$K3SCTL_BASE_URL" \
      -e K3SCTL_MODEL="$K3SCTL_MODEL" \
      "$IMAGE" \
      --kubeconfig=/home/app/.kube/config \
      --insecure-skip-tls-verify \
      "$@"
    ;;
  *)
    echo "Uso: $0 {build|run} [flags-del-agente...]" >&2
    exit 1
    ;;
esac
