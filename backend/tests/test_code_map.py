from app.index.code_map import build_code_map

PY_FILE = '''
import os
from fastapi import APIRouter

from app.services import pedidos_service

router = APIRouter()

TOKEN = os.getenv("API_TOKEN")


@router.get("/pedidos/{pedido_id}")
def obter_pedido(pedido_id: int):
    return pedidos_service.get(pedido_id)


class PedidoRepo:
    def salvar(self, pedido):
        return os.environ["DB_URL"]
'''

TS_FILE = '''
import { soma } from './util';

export class PedidoService {}

export function calcular(total: number) { return total; }

const listar = async (req, res) => res.json([]);

router.post('/pedidos', listar);
const chave = process.env.STRIPE_KEY;
'''


def test_python_symbols_rotas_env():
    cmap = build_code_map([("app/api/pedidos.py", PY_FILE)])
    names = {s.name for f in cmap.files for s in f.symbols}
    assert "obter_pedido" in names
    assert "PedidoRepo" in names
    assert "PedidoRepo.salvar" in names
    assert any(r.method == "get" and r.path == "/pedidos/{pedido_id}" for r in cmap.routes)
    assert {"API_TOKEN", "DB_URL"} <= cmap.env_vars


def test_ts_symbols_rotas_env():
    cmap = build_code_map([("src/pedido.ts", TS_FILE)])
    names = {s.name for f in cmap.files for s in f.symbols}
    assert {"PedidoService", "calcular", "listar"} <= names
    assert any(r.method == "post" and r.path == "/pedidos" for r in cmap.routes)
    assert "STRIPE_KEY" in cmap.env_vars


def test_edges_e_mermaid():
    files = [
        ("app/api/pedidos.py", PY_FILE),
        ("app/services/pedidos_service.py", "def get(pid):\n    return None\n"),
    ]
    cmap = build_code_map(files)
    assert ("app/api/pedidos.py", "app/services/pedidos_service.py") in cmap.edges
    mermaid = cmap.mermaid_dependencies()
    assert mermaid is not None and mermaid.startswith("graph LR")


def test_facts_text_lista_rotas():
    cmap = build_code_map([("app/api/pedidos.py", PY_FILE)])
    facts = cmap.facts_text()
    assert "GET /pedidos/{pedido_id}" in facts
    assert "API_TOKEN" in facts


def test_arquivo_python_invalido_nao_quebra():
    cmap = build_code_map([("quebrado.py", "def ??? sintaxe invalida")])
    assert len(cmap.files) == 1
    assert cmap.files[0].symbols == []
