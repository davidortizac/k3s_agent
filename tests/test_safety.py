"""Tests de clasificación read/mutating (el corazón de la seguridad)."""

import pytest

from k3sctl.safety import classify_kubectl, READ, MUTATING


@pytest.mark.parametrize(
    "args",
    [
        ["get", "pods"],
        ["get", "pods", "-A"],
        ["describe", "node", "k3s-w1"],
        ["logs", "deploy/api"],
        ["top", "nodes"],
        ["events"],
        ["explain", "pod"],
        ["version"],
        ["cluster-info"],
        ["diff", "-f", "manifest.yaml"],
        ["rollout", "status", "deploy/api"],
        ["rollout", "history", "deploy/api"],
        ["config", "view"],
        ["config", "get-contexts"],
        ["auth", "can-i", "get", "pods"],
        ["-n", "kube-system", "get", "pods"],  # flag antes del verbo
    ],
)
def test_read_verbs(args):
    assert classify_kubectl(args) == READ


@pytest.mark.parametrize(
    "args",
    [
        ["apply", "-f", "manifest.yaml"],
        ["delete", "pod", "x"],
        ["scale", "deploy/api", "--replicas=3"],
        ["drain", "node1"],
        ["patch", "deploy/api", "-p", "{}"],
        ["edit", "deploy/api"],
        ["cordon", "node1"],
        ["exec", "-it", "pod", "--", "sh"],
        ["rollout", "restart", "deploy/api"],
        ["rollout", "undo", "deploy/api"],
        ["config", "set", "x", "y"],
        ["auth", "reconcile"],
        ["certificate", "approve", "csr-1"],
        ["frobnicate", "everything"],  # verbo desconocido => peligroso
        ["create", "deployment", "api"],
        ["label", "node", "node1", "env=qa"],
        ["taint", "node", "node1", "dedicated=qa:NoSchedule"],
    ],
)
def test_mutating_verbs(args):
    assert classify_kubectl(args) == MUTATING


def test_empty_is_read():
    assert classify_kubectl([]) == READ
    assert classify_kubectl(["--help"]) == READ
