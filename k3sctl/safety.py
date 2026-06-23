"""Clasificación de comandos en lectura vs. modificación.

Política conservadora: ante la duda, "mutating" (requiere confirmación).
Sin dependencias externas para que sea trivialmente testeable.
"""

from __future__ import annotations

READ = "read"
MUTATING = "mutating"

# Verbos kubectl que solo leen estado.
KUBECTL_READ_VERBS: frozenset[str] = frozenset(
    {
        "get", "describe", "logs", "top", "events", "explain",
        "api-resources", "api-versions", "version", "cluster-info",
        "diff",  # no aplica cambios, solo muestra el delta
        "wait",  # bloquea pero no muta
        "kustomize",
    }
)

# Verbos kubectl que modifican estado (lista explícita, además de los desconocidos).
KUBECTL_MUTATING_VERBS: frozenset[str] = frozenset(
    {
        "apply", "create", "delete", "edit", "patch", "replace", "scale",
        "autoscale", "label", "annotate", "taint", "cordon", "uncordon",
        "drain", "set", "expose", "run", "exec", "cp", "attach",
        "port-forward", "proxy", "evict",
    }
)

# Subcomandos con segundo token que decide la clasificación.
# verbo -> conjunto de segundos tokens que son SOLO lectura; el resto es mutating.
KUBECTL_AMBIGUOUS_READ_SUBVERBS: dict[str, frozenset[str]] = {
    "rollout": frozenset({"status", "history"}),
    "config": frozenset({"view", "get-contexts", "current-context", "get-clusters", "get-users"}),
    "auth": frozenset({"can-i", "whoami"}),
    "certificate": frozenset(),  # approve/deny son mutating -> nunca lectura
}


# Flags GLOBALES de kubectl que consumen el token siguiente cuando se pasan
# separados por espacio (p.ej. `-n kube-system`). Si se usa la forma `--flag=val`
# no aplica (ese token ya empieza por '-'). Lista conservadora de los que pueden
# aparecer ANTES del verbo y confundir la detección.
VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user",
        "--server", "-s", "--token", "--as", "--as-group", "--request-timeout",
        "--tls-server-name", "--cache-dir", "--certificate-authority",
        "--client-certificate", "--client-key", "-o", "--output",
    }
)


def _first_non_flag_tokens(args: list[str]) -> list[str]:
    """Devuelve los tokens posicionales, saltando flags y los valores que estos
    consumen cuando van separados por espacio (p.ej. `-n kube-system`)."""
    positional: list[str] = []
    skip_next = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if tok in VALUE_FLAGS and "=" not in tok:
                skip_next = True
            continue
        positional.append(tok)
    return positional


def classify_kubectl(args: list[str]) -> str:
    """Clasifica una invocación de kubectl (lista de args, sin el binario)."""
    positional = _first_non_flag_tokens(args)
    if not positional:
        # `kubectl` sin verbo, o solo flags (p.ej. `--help`): inofensivo.
        return READ

    verb = positional[0].lower()

    # Subcomandos ambiguos: decide el segundo token.
    if verb in KUBECTL_AMBIGUOUS_READ_SUBVERBS:
        sub = positional[1].lower() if len(positional) > 1 else ""
        read_subs = KUBECTL_AMBIGUOUS_READ_SUBVERBS[verb]
        return READ if sub in read_subs else MUTATING

    if verb in KUBECTL_READ_VERBS:
        return READ
    if verb in KUBECTL_MUTATING_VERBS:
        return MUTATING

    # Verbo desconocido => tratado como peligroso (conservador).
    return MUTATING


def render_kubectl(args: list[str]) -> str:
    """Representación legible (para confirmación/log). No usar para ejecutar."""
    return "kubectl " + " ".join(args)
