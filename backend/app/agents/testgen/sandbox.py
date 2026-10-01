"""Execução isolada dos testes gerados.

Três modos, escolhidos explicitamente por TESTGEN_EXECUTION:

- none:    (padrão) sem execução. Os testes são gerados e validados
           sintaticamente, com aviso claro de que não foram executados.
- docker:  container efêmero, sem rede, com limites de CPU/memória. Se o
           Docker não responder, os testes não são executados.
- local:   subprocess com timeout e ambiente mínimo — só para máquina de dev
           rodando código de confiança do próprio usuário.

Os testes gerados usam unittest (stdlib), então nenhum modo precisa
instalar dependências.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

EXECUTION_TIMEOUT_SECONDS = 60
DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class ExecutionResult:
    mode: str  # docker | local | none
    executed: bool
    passed: bool
    output: str


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return probe.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def resolve_mode() -> str:
    return settings.testgen_execution


def run_unittests(files: dict[str, str]) -> ExecutionResult:
    """Materializa os arquivos num diretório temporário e roda unittest."""
    mode = resolve_mode()
    if mode == "none":
        return ExecutionResult(
            mode="none",
            executed=False,
            passed=False,
            output="execução desabilitada: TESTGEN_EXECUTION=none",
        )
    if mode == "docker" and not _docker_available():
        return ExecutionResult(
            mode="docker",
            executed=False,
            passed=False,
            output="TESTGEN_EXECUTION=docker, mas o Docker não está disponível",
        )

    with tempfile.TemporaryDirectory(prefix="autodoc-testgen-") as tmp:
        root = Path(tmp)
        for rel, content in files.items():
            target = (root / rel).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                return ExecutionResult(mode, False, False, f"Caminho inválido: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        cmd_unittest = ["-m", "unittest", "discover", "-s", ".", "-p", "test_*.py", "-v"]
        try:
            if mode == "docker":
                proc = subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "--network", "none",
                        "--memory", "512m",
                        "--cpus", "1",
                        "--pids-limit", "128",
                        "-v", f"{root}:/work:ro",
                        "-w", "/work",
                        DOCKER_IMAGE,
                        "python", *cmd_unittest,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=EXECUTION_TIMEOUT_SECONDS + 30,
                )
            else:  # local (opt-in)
                proc = subprocess.run(
                    [sys.executable, *cmd_unittest],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=EXECUTION_TIMEOUT_SECONDS,
                    env={
                        "PATH": "",  # nada de binários externos
                        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONIOENCODING": "utf-8",
                    },
                )
        except subprocess.TimeoutExpired:
            return ExecutionResult(mode, True, False, "Timeout: os testes excederam o tempo limite.")
        except OSError as e:
            return ExecutionResult(mode, False, False, f"Falha ao iniciar a execução: {e}")

        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if len(output) > 8_000:
            output = output[-8_000:]
        return ExecutionResult(mode, True, proc.returncode == 0, output)
