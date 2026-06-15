# Documentação Técnica — AutoDoc

| Campo | Valor |
|-------|-------|
| **Projeto** | AutoDoc |
| **Versão do documento** | 1.0 |
| **Última atualização** | 2023-10-01 |
| **Responsável técnico** | Equipe de Desenvolvimento |
| **Ambiente de referência** | Desenvolvimento |
| **Classificação** | Público |

---

## 1. Visão geral

### 1.1 Finalidade da ferramenta

O **AutoDoc** é responsável por gerar documentação de código de forma automatizada, utilizando inteligência artificial para criar templates que facilitam a documentação técnica e funcional de projetos. A ferramenta existe para:

- Aumentar a produtividade na geração de documentação.
- Proporcionar uma interface amigável para usuários gerenciarem templates.
- Permitir a visualização e edição de documentos gerados.

### 1.2 Escopo

| Dentro do escopo | Fora do escopo |
|------------------|----------------|
| Geração de documentação a partir de código | Geração de documentação manual |
| Gerenciamento de templates de documentação | Suporte a múltiplas linguagens de programação |
| Autenticação de usuários | Integração com sistemas externos de controle de versão |

### 1.3 Público-alvo desta documentação

| Público | Objetivo de leitura |
|---------|---------------------|
| Desenvolvedores | Entender como utilizar a ferramenta para gerar documentação |
| Gerentes de projeto | Avaliar a eficácia da ferramenta na documentação de projetos |
| Testadores | Compreender como a documentação é gerada e testada |
| Administradores de sistema | Configurar e manter a ferramenta em ambientes de produção |

---

## 2. Contexto de negócio

O AutoDoc foi desenvolvido para atender à necessidade crescente de documentação eficiente em projetos de software. Com a complexidade crescente dos sistemas, a documentação se torna um aspecto crucial para a manutenção e evolução dos mesmos. A ferramenta visa simplificar esse processo, permitindo que as equipes se concentrem no desenvolvimento, enquanto a documentação é gerada automaticamente.

---

## 3. Arquitetura da solução

### 3.1 Diagrama lógico (alto nível)

```text
[Frontend] <--> [Backend API] <--> [Banco de Dados]
```

### 3.2 Componentes principais

| Componente | Tecnologia | Responsabilidade |
|------------|------------|------------------|
| Frontend | Angular | Interface do usuário e interação com a API |
| Backend API | Node.js | Lógica de negócios e manipulação de dados |
| Banco de Dados | MongoDB | Armazenamento de templates e documentos gerados |

---

## 4. Fluxo de dados (entrada → tratamento → saída)

### 4.1 Resumo do pipeline

```text
Usuário → Frontend (formulário) → Backend API (processamento) → Banco de Dados (armazenamento) → Frontend (exibição)
```

### 4.2 Detalhamento por etapa

| Etapa | Entrada | Processamento | Saída |
|-------|---------|---------------|-------|
| **E1 — Login** | Credenciais do usuário | Verificação no banco de dados | Token de autenticação |
| **E2 — Geração de Documentação** | Código e template selecionado | Processamento da IA | Documento gerado |
| **E3 — Visualização** | ID do documento | Recuperação do documento | Conteúdo do documento |
| **E4 — Edição** | Conteúdo editado | Atualização no banco de dados | Confirmação de sucesso |

### 4.3 Exemplo de consulta na base X

```sql
SELECT * FROM templates WHERE type = 'technical';
```

### 4.4 Exemplo de payload enviado para a API Y

```json
{
  "email": "usuario@exemplo.com",
  "password": "senha123"
}
```

---

## 5. Dados utilizados

### 5.1 Inventário de fontes

| ID | Fonte | Tipo | Dados sensíveis | Retenção na origem |
|----|-------|------|-----------------|-------------------|
| F01 | MongoDB | Banco de dados | Não | Indefinido |
| F02 | API Externa | REST | Sim | 30 dias |

### 5.2 Campos consumidos e finalidade

| Campo | Origem | Tipo | Uso no AutoDoc |
|-------|--------|------|------------------|
| email | Formulário de login | String | Autenticação do usuário |
| password | Formulário de login | String | Autenticação do usuário |
| template_id | Seleção de template | String | Identificação do template a ser utilizado |

### 5.3 Tratamento de dados pessoais (LGPD)

| Medida | Descrição |
|--------|-----------|
| Criptografia | Senhas são armazenadas de forma criptografada. |
| Consentimento | Usuários devem consentir com o tratamento de seus dados. |
| Acesso restrito | Apenas usuários autenticados podem acessar dados sensíveis. |

---

## 6. Regras de negócio e transformações

### 6.1 Regras aplicadas

| Código | Regra | Condição | Ação |
|--------|-------|----------|------|
| R01 | Autenticação | Usuário não autenticado | Redirecionar para login |
| R02 | Geração de documento | Template não encontrado | Retornar erro |

### 6.2 Métricas calculadas

| Métrica | Fórmula / lógica | Unidade |
|---------|------------------|---------|
| Total de documentos gerados | Contagem de registros na coleção de documentos | Documentos |
| Tempo médio de geração | Soma dos tempos de geração / número de documentos gerados | Segundos |

---

## 7. Output final

### 7.1 Artefatos produzidos

| Artefato | Formato | Destino | Disponibilidade |
|----------|---------|---------|-----------------|
| Documentação gerada | Markdown | Download | Imediata |
| Templates | JSON | API | Imediata |

### 7.2 Estrutura do CSV de saída

| Coluna | Tipo | Descrição | Exemplo |
|--------|------|-----------|---------|
| filename | String | Nome do arquivo gerado | "documentacao.md" |
| created_at | Date | Data de criação do documento | "2023-10-01T12:00:00Z" |

### 7.3 Exemplo de resposta da API Y (sucesso)

```json
{
  "message": "Login realizado com sucesso",
  "token": "eyJhbGciOiJIUzI1NiIsInR..."
}
```

---

## 8. Integrações externas

O AutoDoc se integra com APIs de autenticação e serviços de armazenamento em nuvem para gerenciar templates e documentos gerados.

## 9. Configuração e variáveis de ambiente

As variáveis de ambiente necessárias incluem:

- `API_BASE`: URL base da API.
- `DB_CONNECTION_STRING`: String de conexão com o banco de dados.

## 10. Execução e agendamento

### 10.1 Agendamento

Não há agendamentos automáticos implementados até o momento.

### 10.2 Comandos locais (desenvolvimento)

```bash
# Ativar ambiente
ng serve

# Executar job completo
npm run build

# Reprocessar somente publicação (CSV já gerado)
npm run generate
```

## 11. Tratamento de erros e reprocessamento

Erros de autenticação e geração de documentos são tratados com mensagens de erro apropriadas e redirecionamentos quando necessário.

## 12. Monitoramento e SLAs

O sistema deve ser monitorado para garantir que a API esteja disponível 99% do tempo.

## 13. Segurança

- Uso de HTTPS para todas as comunicações.
- Armazenamento seguro de tokens de autenticação.

## 14. Dependências

### 14.1 Software

- Angular
- Node.js
- MongoDB

### 14.2 Equipes e sistemas upstream/downstream

- Equipe de Desenvolvimento
- Equipe de Infraestrutura

## 15. Glossário

- **Template**: Estrutura de documento utilizada para gerar a documentação.
- **Markdown**: Linguagem de marcação utilizada para formatar texto.

## 16. Histórico de revisões

- **2023-10-01**: Criação da documentação inicial.

## 17. Anexos

### Anexo A — Exemplo de registro de auditoria

```json
{
  "action": "login",
  "user": "usuario@exemplo.com",
  "timestamp": "2023-10-01T12:00:00Z"
}
```

### Anexo B — Contatos

- **Equipe de Suporte**: suporte@autodoc.dev
- **Gerente de Projeto**: gerente@autodoc.dev