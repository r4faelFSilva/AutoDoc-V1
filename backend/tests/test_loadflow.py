from app.agents.arquiteto.loadflow import analyze_load

ARCH = {
    "nodes": [
        {"id": "client", "type": "client", "label": "Clientes", "props": {}},
        {"id": "api", "type": "service", "label": "API", "props": {"replicas": 3, "rps_capacity": 300}},
        {"id": "db", "type": "db", "label": "Postgres", "props": {"replicas": 1, "rps_capacity": 400}},
        {"id": "cache", "type": "cache", "label": "Redis", "props": {"replicas": 1, "rps_capacity": 5000}},
    ],
    "edges": [
        {"from": "client", "to": "api", "sync": True, "weight": 1.0},
        {"from": "api", "to": "cache", "sync": True, "weight": 1.0},
        {"from": "api", "to": "db", "sync": True, "weight": 0.5},  # 50% cache miss
    ],
}


def test_propagacao_basica():
    result = analyze_load(ARCH, input_rps=600)
    loads = result["loads"]
    assert loads["client"] == 600
    assert loads["api"] == 600
    assert loads["cache"] == 600
    assert loads["db"] == 300  # weight 0.5


def test_gargalo_detectado():
    # API: 3x300 = 900 de capacidade; 1000 RPS → gargalo high
    result = analyze_load(ARCH, input_rps=1000)
    bottlenecks = [a for a in result["annotations"] if a["kind"] == "bottleneck"]
    assert any(a["target"] == "api" for a in bottlenecks)
    # DB recebe 500 (weight 0.5) com capacidade 400 → também gargalo
    assert any(a["target"] == "db" for a in bottlenecks)


def test_aviso_de_utilizacao_alta():
    # API a 700/900 = 78% → warning, não bottleneck
    result = analyze_load(ARCH, input_rps=700)
    kinds = {(a["target"], a["kind"]) for a in result["annotations"]}
    assert ("api", "warning") in kinds
    assert ("api", "bottleneck") not in kinds


def test_spof_replicca_unica():
    result = analyze_load(ARCH, input_rps=100)
    spofs = {a["target"] for a in result["annotations"] if a["kind"] == "spof"}
    assert "db" in spofs
    assert "cache" in spofs
    assert "api" not in spofs  # 3 réplicas


def test_ciclo_nao_trava():
    arch = {
        "nodes": [
            {"id": "a", "type": "service", "label": "A", "props": {"rps_capacity": 100}},
            {"id": "b", "type": "service", "label": "B", "props": {"rps_capacity": 100}},
        ],
        "edges": [
            {"from": "a", "to": "b", "weight": 0.5},
            {"from": "b", "to": "a", "weight": 0.5},
        ],
    }
    result = analyze_load(arch, input_rps=100)  # não pode entrar em loop infinito
    assert result["loads"]["a"] > 0


def test_sem_capacidade_declarada_nao_afirma_nada():
    arch = {
        "nodes": [
            {"id": "client", "type": "client", "label": "C", "props": {}},
            {"id": "x", "type": "service", "label": "X", "props": {"replicas": 2}},
        ],
        "edges": [{"from": "client", "to": "x", "weight": 1.0}],
    }
    result = analyze_load(arch, input_rps=99999)
    assert all(a["kind"] != "bottleneck" for a in result["annotations"])
