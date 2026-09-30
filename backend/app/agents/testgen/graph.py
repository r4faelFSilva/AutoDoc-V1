"""Agente gerador de testes unitários.

analyze → generate → execute ─(falhou e há tentativas)→ repair → execute…
                        └────────(passou / sem execução)→ report

Agente de API/pipeline — não tem tela própria. Consumidores: pipeline de
CI (gate), MCP na IDE e CLI. O "sandbox" é interno: os testes gerados são
EXECUTADOS (ver sandbox.py) e, se falham, o erro volta ao modelo (reparo).

v1: Python com loop completo (unittest, stdlib); TypeScript/JavaScript em
modo geração-apenas (spec Jasmine, sem execução).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, model_validator

from app.core import contracts, llm
from app.database import SessionLocal
from app.index.code_map import build_code_map
from app.jobs.tasks import emit
from app.models.agent_run import Artifact, Evaluation
from app.agents.testgen import sandbox
from app.services.github_archive import (
    GitHubArchiveError,
    fetch_repo_files,
    parse_github_url,
)

MAX_REPAIR_ATTEMPTS = 2
MAX_SOURCE_CHARS = 30_000


class TestgenInput(BaseModel):
    source: str = Field(pattern="^(paste|upload|github)$")
    code: str | None = Field(default=None, max_length=MAX_SOURCE_CHARS)
    filename: str | None = None
    github_url: str | None = None
    branch: str | None = None
    # arquivo-alvo dentro do repositório (obrigatório no modo github)
    target_path: str | None = None

    @model_validator(mode="after")
    def validate_by_source(self) -> "TestgenInput":
        if self.source == "github":
            if not self.github_url:
                raise ValueError("Informe github_url no modo github.")
            if not self.target_path:
                raise ValueError("Informe target_path: o arquivo do repositório a testar.")
        elif not self.code:
            raise ValueError("Informe o código a testar.")
        return self


class TestgenOutput(BaseModel):
    status: str  # passed | failed | not_executed
    language: str
    execution_mode: str  # docker | local | none
    attempts: int
    test_filename: str
    test_code: str
    summary: str


class TgState(TypedDict, total=False):
    run_id: int
    user_id: int
    source: str
    code: str | None
    filename: str | None
    github_url: str | None
    branch: str | None
    target_path: str | None
    # intermediários
    language: str
    module_name: str
    source_code: str
    symbols_text: str
    test_code: str
    attempts: int
    executed: bool
    passed: bool
    exec_mode: str
    exec_output: str
    output: dict
    usage: dict


def _merge_usage(state_usage: dict | None, result: llm.ChatResult) -> dict:
    usage = dict(state_usage or {})
    usage["model"] = result.model
    usage["input_tokens"] = int(usage.get("input_tokens", 0)) + result.input_tokens
    usage["output_tokens"] = int(usage.get("output_tokens", 0)) + result.output_tokens
    return usage


def _extract_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _module_name(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    name = re.sub(r"[^0-9a-zA-Z_]", "_", stem)
    if not name or name[0].isdigit():
        name = f"modulo_{name}"
    return name


def _detect_language(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        return "typescript"
    raise ValueError("Linguagem não suportada. Use arquivos .py, .ts ou .js.")


# ---------------------------------------------------------------- nós

async def analyze(state: TgState) -> TgState:
    run_id = state["run_id"]

    if state["source"] == "github":
        github_url = state.get("github_url") or ""
        target = (state.get("target_path") or "").strip().lstrip("/")
        await emit(run_id, "progress", f"Buscando `{target}` em {github_url}…")
        try:
            owner, repo, url_branch = parse_github_url(github_url)
            _ref, files, _warnings = await asyncio.to_thread(
                fetch_repo_files,
                owner=owner,
                repo=repo,
                branch=url_branch or state.get("branch"),
                max_files=400,
                max_total_chars=1_200_000,
            )
        except GitHubArchiveError as e:
            raise ValueError(str(e)) from e
        match = next((content for fp, content in files if fp == target), None)
        if match is None:
            raise ValueError(f"Arquivo `{target}` não encontrado no repositório.")
        filename = target
        source_code = match
    else:
        filename = state.get("filename") or "codigo.py"
        source_code = state.get("code") or ""

    language = _detect_language(filename)
    if language == "python":
        try:
            ast.parse(source_code)
        except SyntaxError as e:
            raise ValueError(f"O código-fonte tem erro de sintaxe: {e}") from e

    cmap = build_code_map([(filename, source_code)])
    symbols = [s.signature for f in cmap.files for s in f.symbols]
    module = _module_name(filename)

    await emit(
        run_id,
        "node_finished",
        f"Análise concluída: {len(symbols)} símbolos em `{filename}` ({language}).",
        data={"symbols": symbols[:20]},
    )
    return {
        "language": language,
        "module_name": module,
        "source_code": source_code[:MAX_SOURCE_CHARS],
        "symbols_text": "\n".join(f"- {s}" for s in symbols[:30]) or "- (nenhum símbolo detectado)",
        "filename": filename,
        "attempts": 0,
    }


def _gen_system(state: TgState) -> str:
    if state["language"] == "python":
        return (
            "Você escreve testes unitários Python usando APENAS `unittest` da biblioteca padrão.\n"
            'Responda APENAS com JSON válido: {"test_code": string}\n\n'
            "Regras obrigatórias:\n"
            f"- Importe o alvo com `from {state['module_name']} import ...` "
            "(o módulo estará no mesmo diretório).\n"
            "- Nenhuma dependência externa; nenhum acesso a rede, arquivos ou variáveis de ambiente.\n"
            "- Se o módulo importar bibliotecas de terceiros, use unittest.mock para isolá-las.\n"
            "- Cubra comportamento principal e casos de borda dos símbolos públicos.\n"
            "- Métodos de teste com nomes descritivos em português (test_calcula_frete_com_peso_zero).\n"
            "- O arquivo deve ser executável com `python -m unittest`."
        )
    return (
        "Você escreve testes unitários TypeScript no estilo Jasmine (describe/it/expect), "
        "como usado por projetos Angular.\n"
        'Responda APENAS com JSON válido: {"test_code": string}\n'
        "Importe o alvo por caminho relativo './" + state["module_name"] + "'. "
        "Sem dependências além do Jasmine. Cubra comportamento principal e casos de borda."
    )


async def generate(state: TgState) -> TgState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Gerando testes unitários…")
    provider = llm.get_provider()
    user = (
        f"Arquivo alvo: `{state['filename']}`\n"
        f"Símbolos públicos:\n{state['symbols_text']}\n\n"
        f"Código-fonte:\n```\n{state['source_code']}\n```"
    )
    result = await provider.chat(
        system_prompt=_gen_system(state),
        user_content=user,
        json_mode=True,
        max_output_tokens=3500,
        temperature=0.2,
    )
    data = _extract_json(result.text)
    test_code = str(data.get("test_code") or "").strip()
    if not test_code:
        raise ValueError("O modelo não retornou código de teste.")
    await emit(run_id, "node_finished", "Testes gerados.")
    return {"test_code": test_code, "usage": _merge_usage(state.get("usage"), result)}


async def execute(state: TgState) -> TgState:
    run_id = state["run_id"]

    if state["language"] != "python":
        await emit(
            run_id,
            "node_finished",
            "Execução pulada: TypeScript/JavaScript é geração-apenas nesta versão.",
        )
        return {"executed": False, "passed": False, "exec_mode": "none", "exec_output": ""}

    # validação sintática antes de gastar execução
    try:
        ast.parse(state["test_code"])
    except SyntaxError as e:
        await emit(run_id, "progress", f"Teste com erro de sintaxe ({e.lineno}): indo para reparo…")
        return {
            "executed": True,  # conta como tentativa
            "passed": False,
            "exec_mode": "syntax",
            "exec_output": f"SyntaxError no arquivo de teste: {e}",
        }

    await emit(run_id, "progress", "Executando os testes gerados…")
    files = {
        f"{state['module_name']}.py": state["source_code"],
        f"test_{state['module_name']}.py": state["test_code"],
    }
    result = await asyncio.to_thread(sandbox.run_unittests, files)
    if not result.executed:
        await emit(run_id, "node_finished", f"Testes não executados: {result.output}")
    else:
        await emit(
            run_id,
            "node_finished",
            "Testes " + ("PASSARAM." if result.passed else "FALHARAM."),
            data={"mode": result.mode},
        )
    return {
        "executed": result.executed,
        "passed": result.passed,
        "exec_mode": result.mode,
        "exec_output": result.output,
    }


async def repair(state: TgState) -> TgState:
    run_id = state["run_id"]
    attempts = int(state.get("attempts", 0)) + 1
    await emit(run_id, "progress", f"Reparando testes (tentativa {attempts})…")
    provider = llm.get_provider()
    system = (
        "Você corrige um arquivo de testes `unittest` que falhou ao executar.\n"
        'Responda APENAS com JSON válido: {"test_code": string}\n'
        "Corrija o TESTE, não o código-fonte. Se o teste assumia comportamento que o código "
        "não tem, ajuste a asserção ao comportamento real do código. Mantenha as mesmas regras "
        "(somente unittest, sem dependências externas)."
    )
    user = (
        f"Módulo `{state['module_name']}`:\n```\n{state['source_code']}\n```\n\n"
        f"Teste atual:\n```\n{state['test_code']}\n```\n\n"
        f"Saída da execução que falhou:\n```\n{state['exec_output'][:4_000]}\n```"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=3500, temperature=0.2
    )
    data = _extract_json(result.text)
    test_code = str(data.get("test_code") or "").strip() or state["test_code"]
    return {
        "test_code": test_code,
        "attempts": attempts,
        "usage": _merge_usage(state.get("usage"), result),
    }


async def report(state: TgState) -> TgState:
    run_id = state["run_id"]
    ext = ".py" if state["language"] == "python" else ".spec.ts"
    test_filename = f"test_{state['module_name']}{ext}" if state["language"] == "python" else f"{state['module_name']}.spec.ts"

    if state["language"] != "python":
        status = "not_executed"
        summary = "Testes Jasmine gerados; execução de TS ainda não é suportada — rode com `ng test`."
    elif not state.get("executed"):
        status = "not_executed"
        summary = (
            "Testes gerados e com sintaxe válida, mas NÃO executados "
            f"({state.get('exec_output', '')}). Rode-os antes de confiar."
        )
    elif state.get("passed"):
        status = "passed"
        summary = f"Testes executados e aprovados (modo {state['exec_mode']}, {state.get('attempts', 0)} reparos)."
    else:
        status = "failed"
        summary = (
            f"Testes ainda falham após {state.get('attempts', 0)} reparos. "
            "Saída anexada — pode indicar bug real no código-alvo."
        )

    db = SessionLocal()
    try:
        db.add(
            Artifact(
                run_id=run_id,
                kind="tests",
                name=test_filename,
                content=state["test_code"],
                created_at=datetime.utcnow(),
            )
        )
        if state.get("exec_output"):
            db.add(
                Artifact(
                    run_id=run_id,
                    kind="test_execution",
                    name="execucao.log",
                    content=state["exec_output"],
                    created_at=datetime.utcnow(),
                )
            )
        for metric, value in (
            ("tests_passed", 1.0 if status == "passed" else 0.0),
            ("tests_executed", 1.0 if state.get("executed") else 0.0),
            ("repair_attempts", float(state.get("attempts", 0))),
        ):
            db.add(Evaluation(run_id=run_id, metric=metric, score=value, created_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    output = TestgenOutput(
        status=status,
        language=state["language"],
        execution_mode=state.get("exec_mode", "none"),
        attempts=int(state.get("attempts", 0)),
        test_filename=test_filename,
        test_code=state["test_code"],
        summary=summary,
    )
    return {"output": output.model_dump()}


def _after_execute(state: TgState) -> str:
    if state["language"] != "python":
        return "report"
    if not state.get("executed"):
        return "report"
    if state.get("passed"):
        return "report"
    if int(state.get("attempts", 0)) < MAX_REPAIR_ATTEMPTS:
        return "repair"
    return "report"


def build_graph():
    g = StateGraph(TgState)
    g.add_node("analyze", analyze)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("repair", repair)
    g.add_node("report", report)

    g.set_entry_point("analyze")
    g.add_edge("analyze", "generate")
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", _after_execute, {"repair": "repair", "report": "report"})
    g.add_edge("repair", "execute")
    g.add_edge("report", END)
    return g.compile()


SPEC = contracts.register(
    contracts.AgentSpec(
        name="gerador_testes",
        title="Gerador de Testes",
        description=(
            "Gera testes unitários (unittest para Python, Jasmine para TS), executa em ambiente "
            "isolado e repara falhas automaticamente. Agente de pipeline/IDE — sem tela própria."
        ),
        input_schema=TestgenInput,
        output_schema=TestgenOutput,
        build_graph=build_graph,
    )
)
