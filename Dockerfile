# syntax=docker/dockerfile:1
# Imagen base sin la restricción PEP 668 (a diferencia de Ubuntu/Debian modernos),
# por la lección aprendida nº3 del encargo.
FROM python:3.12-slim AS base

# --- argumentos de versión (verifica antes de fijar) ---
ARG KUBECTL_VERSION=v1.31.0
ARG HELM_VERSION=v3.16.2
ARG TARGETARCH=amd64

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    K3SCTL_HOME=/home/app/.k3sctl

# --- binarios del cluster: kubectl (estable) y helm (opcional) ---
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    curl -fsSL -o /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl"; \
    chmod +x /usr/local/bin/kubectl; \
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" \
        | tar -xz -C /tmp; \
    mv "/tmp/linux-${TARGETARCH}/helm" /usr/local/bin/helm; \
    chmod +x /usr/local/bin/helm; \
    apt-get purge -y curl; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /tmp/linux-*

# --- dependencias Python (capa cacheable) ---
WORKDIR /app
COPY pyproject.toml README.md ./
COPY k3sctl ./k3sctl
RUN pip install .

# --- usuario no-root ---
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /home/app/.k3sctl /home/app/.kube \
    && chown -R app:app /home/app
USER app
WORKDIR /home/app

# La TUI exige TTY: ejecutar con `docker run -it`.
# ENTRYPOINT fijo + CMD vacío => se pueden pasar flags como argumentos de `docker run`.
ENTRYPOINT ["k3sctl"]
CMD []
