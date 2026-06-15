# Documentação Técnica — Sistema NexusSync

| Campo | Valor |
|-------|-------|
| **Projeto** | NexusSync — Integração de Relatórios Operacionais |
| **Versão do documento** | 1.0.0 |
| **Última atualização** | 14/06/2026 |
| **Responsável técnico** | Equipe Plataforma de Dados — Grupo Atlas |
| **Ambiente de referência** | Homologação (Azure) / Produção (Azure) |
| **Classificação** | Uso interno |

---

## 1. Visão geral

### 1.1 Finalidade da ferramenta

O **NexusSync** é um serviço batch-orquestrado responsável por consolidar indicadores operacionais de múltiplas fontes, aplicar regras de negócio padronizadas e publicar relatórios estruturados para consumo por APIs corporativas e dashboards analíticos.

A ferramenta existe para:

- Reduzir retrabalho manual na geração de relatórios semanais de performance logística.
- Garantir rastreabilidade entre a origem dos dados, as transformações aplicadas e o artefato final entregue.
- Centralizar o envio de payloads validados para sistemas downstream (BI, alertas e arquivamento).

### 1.2 Escopo

| Dentro do escopo | Fora do escopo |
|------------------|----------------|
| Extração de dados das bases `DB_OPERACOES` e `DB_CLIENTES` | Interface gráfica para usuários finais |
| Normalização, enriquecimento e agregação de métricas | Cálculo de folha de pagamento |
| Geração de arquivo CSV e envio para API externa | Treinamento de modelos de machine learning |
| Registro de auditoria e notificação de falhas | Edição manual de registros na base de origem |

### 1.3 Público-alvo desta documentação

| Público | Objetivo de leitura |
|---------|---------------------|
| Desenvolvedores | Manutenção, evolução e troubleshooting |
| Analistas de dados | Compreensão das regras de transformação |
| Sustentação / NOC | Monitoramento, reprocessamento e incidentes |
| Arquitetos | Avaliação de integrações e dependências |

---

## 2. Contexto de negócio

A área de **Operações Logísticas** consolida, toda segunda-feira até 08:00, um painel com indicadores de:

- Tempo médio de expedição por região.
- Taxa de pedidos com atraso acima do SLA contratado.
- Volume financeiro movimentado por canal de venda.

Antes do NexusSync, esse processo dependia de planilhas manuais e consultas ad hoc, gerando inconsistência entre filiais e atraso na disponibilização dos números para a diretoria.

---

## 3. Arquitetura da solução

### 3.1 Diagrama lógico (alto nível)

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  DB_OPERACOES   │────▶│                  │     │  API Gateway Corp   │
│  (SQL Server)   │     │    NexusSync     │────▶│  /v1/relatorios     │
└─────────────────┘     │   (Python 3.11)  │     └──────────┬──────────┘
                        │                  │                │
┌─────────────────┐     │  • ETL           │                ▼
│  DB_CLIENTES    │────▶│  • Validação     │     ┌─────────────────────┐
│  (PostgreSQL)   │     │  • Export CSV    │     │  Power BI / Alertas │
└─────────────────┘     └────────┬─────────┘     └─────────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ Blob Storage     │
                        │ /relatorios/     │
                        └──────────────────┘
```

### 3.2 Componentes principais

| Componente | Tecnologia | Responsabilidade |
|------------|------------|------------------|
| Orquestrador | Azure DevOps Pipeline | Disparo agendado, variáveis de ambiente, retry |
| Worker ETL | Python + Pandas | Leitura, transformação e montagem do dataset |
| Camada de acesso | SQLAlchemy + psycopg2/pyodbc | Conexão com bases relacionais |
| Cliente HTTP | `httpx` | Publicação do payload na API corporativa |
| Armazenamento | Azure Blob Storage | Persistência do CSV gerado |
| Observabilidade | Application Insights + Teams Webhook | Logs, métricas e alertas de falha |

---

## 4. Fluxo de dados (entrada → tratamento → saída)

### 4.1 Resumo do pipeline

```text
SELECT base X  →  tratamentos  →  validação  →  output CSV  →  POST API Y  →  blob + log
```

### 4.2 Detalhamento por etapa

| Etapa | Entrada | Processamento | Saída |
|-------|---------|---------------|-------|
| **E1 — Extração Operações** | Tabela `fato_expedicao` (`DB_OPERACOES`) | `SELECT` com filtro de janela de 7 dias e status `CONCLUIDO` | DataFrame `df_ops` |
| **E2 — Extração Clientes** | Tabela `dim_cliente` (`DB_CLIENTES`) | `SELECT` de segmento, região e flag premium | DataFrame `df_cli` |
| **E3 — Enriquecimento** | `df_ops`, `df_cli` | `merge` por `cliente_id`, preenchimento de região ausente com `NAO_INFORMADO` | DataFrame `df_enriched` |
| **E4 — Agregação** | `df_enriched` | Group by `regiao`, `canal_venda`; métricas: média SLA, soma valor, contagem pedidos | DataFrame `df_agg` |
| **E5 — Validação** | `df_agg` | Regras: campos obrigatórios, tipos numéricos, limites máximos | Relatório de qualidade + `df_valid` |
| **E6 — Exportação** | `df_valid` | Geração de CSV UTF-8 com separador `;` | Arquivo `relatorio_ops_YYYYMMDD.csv` |
| **E7 — Publicação API** | CSV + metadados JSON | `POST` autenticado para API Gateway | HTTP 202 + `job_id` |
| **E8 — Arquivamento** | CSV | Upload para container `relatorios` | URL assinada (SAS) |
| **E9 — Auditoria** | Metadados da execução | Insert em `log_execucao_nexussync` | Registro persistido |

### 4.3 Exemplo de consulta na base X

```sql
-- DB_OPERACOES.dbo.fato_expedicao
SELECT
    pedido_id,
    cliente_id,
    canal_venda,
    data_expedicao,
    minutos_sla,
    valor_pedido,
    status
FROM dbo.fato_expedicao
WHERE data_expedicao >= DATEADD(day, -7, GETDATE())
  AND status = 'CONCLUIDO';
```

### 4.4 Exemplo de payload enviado para a API Y

```json
{
  "origem": "NexusSync",
  "tipo_relatorio": "OPERACOES_SEMANAL",
  "referencia": "2026-W24",
  "gerado_em": "2026-06-14T07:45:00Z",
  "total_registros": 1284,
  "checksum_sha256": "a1b2c3d4e5f6789012345678901234567890abcd",
  "arquivo": {
    "nome": "relatorio_ops_20260614.csv",
    "formato": "text/csv",
    "encoding": "utf-8"
  }
}
```

---

## 5. Dados utilizados

### 5.1 Inventário de fontes

| ID | Fonte | Tipo | Dados sensíveis | Retenção na origem |
|----|-------|------|-----------------|-------------------|
| F01 | `DB_OPERACOES.fato_expedicao` | SQL Server | Não (dados operacionais) | 24 meses |
| F02 | `DB_CLIENTES.dim_cliente` | PostgreSQL | Sim (PII: nome, documento) | Conforme LGPD — 5 anos |
| F03 | Azure Key Vault | Segredos | Sim (connection strings, tokens) | Rotação trimestral |
| F04 | API Gateway `/oauth/token` | REST | Sim (client_secret) | Não persistido localmente |

### 5.2 Campos consumidos e finalidade

| Campo | Origem | Tipo | Uso no NexusSync |
|-------|--------|------|------------------|
| `pedido_id` | F01 | UUID | Chave de rastreio e deduplicação |
| `cliente_id` | F01 / F02 | INT | Join entre operações e cadastro |
| `regiao` | F02 | VARCHAR(40) | Dimensão de agregação geográfica |
| `canal_venda` | F01 | ENUM | Segmentação do relatório |
| `minutos_sla` | F01 | INT | Cálculo de indicadores de atraso |
| `valor_pedido` | F01 | DECIMAL(12,2) | Soma financeira por região/canal |
| `segmento_cliente` | F02 | VARCHAR(20) | Enriquecimento analítico (não exportado na API Y) |

### 5.3 Tratamento de dados pessoais (LGPD)

| Medida | Descrição |
|--------|-----------|
| Minimização | Apenas `cliente_id` trafega no CSV final; nome e documento não são exportados |
| Pseudonimização | Identificadores numéricos substituem nomes em logs de aplicação |
| Base legal | Execução de contrato e legítimo interesse operacional (registro interno nº 2024-OP-017) |
| Retenção do output | CSV no Blob Storage: 90 dias; logs de auditoria: 12 meses |

---

## 6. Regras de negócio e transformações

### 6.1 Regras aplicadas

| Código | Regra | Condição | Ação |
|--------|-------|----------|------|
| RN-001 | Pedido atrasado | `minutos_sla > 240` | Marca flag `atraso_critico = true` |
| RN-002 | Região ausente | `regiao IS NULL` | Preenche com `NAO_INFORMADO` |
| RN-003 | Valor inválido | `valor_pedido <= 0` | Exclui registro e incrementa contador de rejeição |
| RN-004 | Cliente inativo | `status_cliente = 'INATIVO'` | Mantém no agregado, mas exclui do total premium |
| RN-005 | Canal desconhecido | `canal_venda NOT IN (...)` | Normaliza para `OUTROS` |

### 6.2 Métricas calculadas

| Métrica | Fórmula / lógica | Unidade |
|---------|------------------|---------|
| `tempo_medio_sla` | Média aritmética de `minutos_sla` por região | minutos |
| `taxa_atraso` | `(pedidos_atrasados / total_pedidos) * 100` | % |
| `valor_total` | Soma de `valor_pedido` | BRL |
| `pedidos_premium` | Contagem onde `segmento_cliente = 'PREMIUM'` | inteiro |

---

## 7. Output final

### 7.1 Artefatos produzidos

| Artefato | Formato | Destino | Disponibilidade |
|----------|---------|---------|-----------------|
| Relatório consolidado | CSV (`;`, UTF-8) | Blob Storage + anexo lógico na API | Segunda-feira, 08:30 |
| Metadados de publicação | JSON | API Gateway `/v1/relatorios` | Imediato após validação |
| Log de execução | JSON estruturado | Application Insights + tabela `log_execucao_nexussync` | Permanente (12 meses) |
| Alerta de falha | Adaptive Card | Microsoft Teams — canal `#ops-alertas` | Em caso de erro |

### 7.2 Estrutura do CSV de saída

| Coluna | Tipo | Descrição | Exemplo |
|--------|------|-----------|---------|
| `referencia_semana` | string | Semana ISO de referência | `2026-W24` |
| `regiao` | string | Região comercial | `SUDESTE` |
| `canal_venda` | string | Canal normalizado | `ECOMMERCE` |
| `total_pedidos` | int | Quantidade de pedidos | `842` |
| `pedidos_atrasados` | int | Pedidos com SLA > 240 min | `37` |
| `taxa_atraso_pct` | decimal | Percentual de atraso | `4.39` |
| `tempo_medio_sla_min` | decimal | Média de SLA | `186.4` |
| `valor_total_brl` | decimal | Soma financeira | `1289045.70` |

### 7.3 Exemplo de resposta da API Y (sucesso)

```json
{
  "status": "accepted",
  "job_id": "job_9f3a21bc-7744-4a91-9e2d-88c1a0f2e6aa",
  "mensagem": "Relatório enfileirado para ingestão analítica.",
  "previsao_processamento": "2026-06-14T08:00:00Z"
}
```

---

## 8. Integrações externas

| Sistema | Protocolo | Endpoint / Recurso | Autenticação | Timeout |
|---------|-----------|-------------------|--------------|---------|
| DB_OPERACOES | TDS (SQL Server) | `sql-operacoes-hml.database.windows.net` | Usuário de serviço + Key Vault | 30s |
| DB_CLIENTES | PostgreSQL | `pg-clientes-hml.postgres.database.azure.com` | Usuário de serviço + Key Vault | 30s |
| API Gateway Corp | HTTPS REST | `https://api-gateway.corp.local/v1/relatorios` | OAuth 2.0 Client Credentials | 60s |
| Blob Storage | HTTPS | `https://example.blob.core.windows.net/relatorios` | Managed Identity | 120s |
| Teams Webhook | HTTPS | URL configurada em `TEAMS_WEBHOOK_URL` | Secret no Key Vault | 15s |

---

## 9. Configuração e variáveis de ambiente

| Variável | Obrigatória | Exemplo | Descrição |
|----------|-------------|---------|-----------|
| `DB_OPERACOES_URL` | Sim | `mssql+pyodbc://...` | Connection string SQL Server |
| `DB_CLIENTES_URL` | Sim | `postgresql+psycopg2://...` | Connection string PostgreSQL |
| `API_GATEWAY_BASE_URL` | Sim | `https://api-gateway.corp.local` | Base URL da API Y |
| `API_GATEWAY_CLIENT_ID` | Sim | `nexussync-hml` | Client ID OAuth |
| `API_GATEWAY_CLIENT_SECRET` | Sim | *(Key Vault)* | Secret OAuth |
| `BLOB_CONTAINER` | Sim | `relatorios` | Container de arquivamento |
| `TEAMS_WEBHOOK_URL` | Não | `https://...` | Alertas de falha |
| `JANELA_DIAS` | Não | `7` | Janela de extração (default: 7) |

---

## 10. Execução e agendamento

### 10.1 Agendamento

| Ambiente | Cron (UTC) | Equivalente (BRT) | Pipeline |
|----------|------------|---------------------|----------|
| Homologação | `0 10 * * 1` | Segunda 07:00 | `nexussync-hml-weekly` |
| Produção | `0 10 * * 1` | Segunda 07:00 | `nexussync-prd-weekly` |

### 10.2 Comandos locais (desenvolvimento)

```bash
# Ativar ambiente
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Executar job completo
python -m nexussync run --env hml --referencia 2026-W24

# Reprocessar somente publicação (CSV já gerado)
python -m nexussync publish --arquivo ./out/relatorio_ops_20260614.csv
```

---

## 11. Tratamento de erros e reprocessamento

| Código | Situação | Comportamento | Ação recomendada |
|--------|----------|---------------|------------------|
| `E-DB-001` | Falha de conexão com base X | Retry 3x (backoff 30s) | Verificar firewall e credenciais |
| `E-DB-002` | Query retornou zero registros | Aborta com alerta Teams | Validar janela de datas |
| `E-VAL-001` | Mais de 5% de registros rejeitados | Aborta antes da API Y | Revisar qualidade na origem |
| `E-API-401` | Token OAuth inválido | Aborta imediato | Rotacionar secret no Key Vault |
| `E-API-500` | Erro downstream | Retry 2x; se persistir, alerta | Acionar sustentação da API Y |
| `E-BLOB-001` | Falha no upload | Continua se API Y OK; alerta warning | Reprocessar arquivamento |

---

## 12. Monitoramento e SLAs

| Indicador | Meta | Medição |
|-----------|------|---------|
| Disponibilidade do job semanal | ≥ 99% | Execuções bem-sucedidas / total |
| Tempo total do pipeline | ≤ 25 min | Início E1 → confirmação E7 |
| Taxa de rejeição na validação | ≤ 2% | Registros rejeitados / extraídos |
| Latência API Y (p95) | ≤ 3s | Application Insights |

---

## 13. Segurança

| Controle | Implementação |
|----------|---------------|
| Segredos | Azure Key Vault; nunca commitados em repositório |
| Tráfego | TLS 1.2+ em todas as integrações HTTP |
| Privilégios de banco | Usuário `svc_nexussync` com permissão somente leitura |
| Logs | Sem PII; mascaramento de tokens e connection strings |
| Auditoria | Tabela `log_execucao_nexussync` com usuário de serviço e hash do arquivo |

---

## 14. Dependências

### 14.1 Software

| Dependência | Versão mínima | Finalidade |
|-------------|---------------|------------|
| Python | 3.11 | Runtime |
| pandas | 2.2.x | Transformações tabulares |
| SQLAlchemy | 2.0.x | Acesso a dados |
| httpx | 0.27.x | Cliente HTTP assíncrono |
| azure-storage-blob | 12.x | Upload de CSV |

### 14.2 Equipes e sistemas upstream/downstream

| Relação | Sistema / Equipe | Impacto se indisponível |
|---------|------------------|-------------------------|
| Upstream | DB_OPERACOES (DBA Operações) | Job não inicia extração |
| Upstream | DB_CLIENTES (Cadastro) | Enriquecimento incompleto |
| Downstream | API Gateway / BI | Relatório não aparece no painel |
| Downstream | Blob Storage | Perda de arquivamento (API pode seguir) |

---

## 15. Glossário

| Termo | Definição |
|-------|-----------|
| **SLA** | Service Level Agreement — acordo de nível de serviço medido em minutos neste contexto |
| **ETL** | Extract, Transform, Load — extração, transformação e carga de dados |
| **Payload** | Corpo de dados enviado em uma requisição HTTP |
| **Downstream** | Sistemas consumidores do output do NexusSync |
| **Janela de extração** | Intervalo de dias considerado na consulta à base de origem |

---

## 16. Histórico de revisões

| Versão | Data | Autor | Descrição |
|--------|------|-------|-----------|
| 0.1.0 | 10/05/2026 | Ana Ribeira | Rascunho inicial |
| 0.9.0 | 02/06/2026 | Carlos Mendes | Inclusão de regras RN-004 e RN-005 |
| 1.0.0 | 14/06/2026 | Equipe Plataforma de Dados | Versão homologada para produção |

---

## 17. Anexos

### Anexo A — Exemplo de registro de auditoria

```json
{
  "execucao_id": "exec_20260614_074500",
  "status": "SUCCESS",
  "referencia": "2026-W24",
  "registros_extraidos": 15420,
  "registros_validos": 15108,
  "registros_rejeitados": 312,
  "arquivo_csv": "relatorio_ops_20260614.csv",
  "api_job_id": "job_9f3a21bc-7744-4a91-9e2d-88c1a0f2e6aa",
  "duracao_segundos": 892
}
```

### Anexo B — Contatos

| Papel | Nome | Canal |
|-------|------|-------|
| Product Owner | Marina Duarte | marina.duarte@empresa-ficticia.local |
| Tech Lead | Carlos Mendes | teams:@carlos.mendes |
| Sustentação | NOC Plataforma | `#noc-plataforma` |
