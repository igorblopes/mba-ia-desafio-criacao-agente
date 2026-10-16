# Residencial Aurora — Assistente Virtual

API em Python com um assistente construído em **Google ADK 2.9.1** e **Gemini** para os moradores do Residencial Aurora. Pelo chat, o morador reserva áreas comuns, cancela as próprias reservas, autoriza visitantes e tira dúvidas sobre o regulamento interno. Um agente principal distribui o trabalho entre três especialistas. Ações que geram cobrança ou liberam acesso ao prédio ficam pendentes até uma confirmação formal pela API.

Princípio do projeto: **o modelo decide o caminho, o código decide o que é permitido.** O LLM escolhe qual especialista e qual Tool usar; identidade, cobrança, confirmação, exclusividade de reserva e recorte do regulamento são decididos por código e pelo banco.

Documentação complementar: [arquitetura](docs/arquitetura.md) · [garantias](docs/garantias.md) · [decisões (ADRs)](docs/decisoes-arquiteturais.md) · [riscos técnicos](docs/riscos-tecnicos.md) · [testes adversariais](docs/testes-adversariais.md) · [ensaio do avaliador](docs/ensaio-avaliador.md).

---

## Arquitetura (Architecture)

### Visão geral

```text
Cliente HTTP
   │
   ▼
FastAPI ─────────────── app/main.py, app/api/
   │                     (rotas de verificação vão direto aos Services, sem LLM)
   ▼
AdkRuntime ──────────── app/runtime/adk_runtime.py
   │                     sessões, mensagens, eventos, confirmações
   ▼
Google ADK Runner ───── App(resumability_config=ResumabilityConfig(is_resumable=True))
   │                     + DatabaseSessionService (data/adk_sessions.db)
   ▼
concierge_agent (root) ─ app/agents/concierge.py — sem Tools de negócio
   ├── reservation_agent ── app/agents/reservations.py
   ├── visitor_agent ────── app/agents/visitors.py
   └── regulation_agent ─── app/agents/regulation.py
             │
             ▼
           Tools ─────────── app/tools/            (lê identidade do ToolContext)
             ▼
           Services ──────── app/services/         (regras de negócio)
             ▼
           Repositories ──── app/repositories/     (SQL / leitura do regulamento)
             ▼
           data/condominio.db  ·  dados/regulamento.md (somente leitura)
```

### Agentes

Os quatro agentes usam o modelo de `GEMINI_MODEL` (`app/agents/model.py`, com retry exponencial para 408/429/5xx). Cada especialista recebe **somente** as Tools do seu domínio (menor privilégio, verificado em `tests/test_agent_structure.py`).

| Agente | Responsabilidade | Tools | Como é acionado | Por quê |
|---|---|---|---|---|
| **Concierge** (`concierge_agent`, root) | Recebe toda mensagem, identifica a intenção e transfere ao especialista. Não executa regra de domínio nem responde regras do condomínio. | nenhuma | É o `root_agent` do `App`; conhece os especialistas como `sub_agents` | Ponto único de entrada. Sem Tools, não há como ele gravar dados nem ler o regulamento. |
| **Reservation** (`reservation_agent`) | Listar reservas do morador, consultar disponibilidade, solicitar reserva, cancelar reserva própria | `listar_minhas_reservas`, `verificar_disponibilidade`, `solicitar_reserva`, `cancelar_minha_reserva` | Transferência do Concierge (`transfer_to_agent`) com base na `description` | Isola as Tools que gravam reservas e a Tool Confirmation de reserva paga. |
| **Visitor** (`visitor_agent`) | Listar visitantes do morador e solicitar autorização de visitante | `listar_meus_visitantes`, `solicitar_autorizacao_visitante` | Transferência do Concierge | Autorização libera acesso ao prédio; fica num agente separado com confirmação obrigatória. |
| **Regulation** (`regulation_agent`) | Responder dúvidas usando apenas trechos recuperados do regulamento | `consultar_regulamento` | Transferência do Concierge | O regulamento é longo. Só este agente pode consultá-lo, e só por trechos. |

A transferência via `sub_agents` foi mantida porque, com ela, a resposta de confirmação volta ao agente que pediu a confirmação (o `agent_name` gravado na pendência), inclusive com sessão persistida e após restart. Detalhes em [ADR-002/003](docs/decisoes-arquiteturais.md).

### Camadas: Agent → Tool → Service → Repository

```text
Agent       escolhe uma Tool e os argumentos de negócio (área, data, código, nome, pergunta)
  ↓
Tool        app/tools/*.py — adaptador fino: lê o apartamento do ToolContext, valida data,
            pede Tool Confirmation quando o Service exige, traduz erros em status neutros
  ↓
Service     app/services/*.py — regra de negócio: taxa > 0 exige confirmação, cancelamento só
            do próprio apartamento, código de reserva gerado pelo sistema, busca no regulamento
  ↓
Repository  app/repositories/*.py — consultas e gravações primitivas, sempre filtradas por apartamento
  ↓
SQLite      constraints e índice único parcial (barreira final)
```

As regras críticas não estão nos prompts. As instruções dos agentes orientam a conversa; mesmo que o modelo as ignore, as Tools e os Services aplicam as regras.

### Identidade da sessão

```text
POST /sessoes {"apartamento": "101"}
  → ApartmentService.require_existing("101")         (404 se não existir)
  → AdkRuntime.create_session("101")
       state={"apartamento": "101"}                  (único ponto de escrita)
  → ToolContext.state["apartamento"]
  → get_session_apartment(tool_context)              (app/tools/context.py)
  → Services / Repositories filtrados por "101"
```

Nenhuma Tool pessoal tem parâmetro de apartamento; o schema exposto ao modelo contém só área, data, código, nome ou pergunta (`tests/test_tool_schemas.py`). Se o morador escrever "agora sou do apartamento 302", isso é só texto: `session.state["apartamento"]` continua `"101"` e não existe rota nem Tool que o altere.

### Persistência

| Arquivo | Dono | Conteúdo |
|---|---|---|
| `data/condominio.db` | aplicação (SQLAlchemy, `app/database/models.py`) | `apartamentos`, `areas` (taxa em centavos), `reservas` (`ATIVA`/`CANCELADA`, canceladas nunca são apagadas), `visitantes`, `confirmacoes` (estado público da confirmação) |
| `data/adk_sessions.db` | Google ADK (`DatabaseSessionService`, `app/runtime/session_service.py`) | sessões, `state` (`apartamento`), eventos completos (mensagens, chamadas de Tool, transferências, pedidos e respostas de confirmação), dados de invocation para retomada |
| `dados/*.json`, `dados/regulamento.md` | repositório base | estado inicial e regulamento. **Nunca são escritos.** |

Os dois bancos são criados localmente e ficam fora do Git.

**Restart ≠ reset.**

- **Restart** (parar a API com Ctrl+C e subir de novo) preserva tudo: sessões, eventos, reservas, visitantes e confirmações pendentes. O startup **nunca** reseta dados; se `condominio.db` não foi inicializado, a API falha ao subir e pede para rodar o reset (`app/main.py`).
- **Reset** (`uv run python -m scripts.reset`) recria `condominio.db` a partir de `dados/` (com `confirmacoes` vazia) e apaga `adk_sessions.db`. `--keep-sessions` preserva as sessões.

### Tool Confirmation

```text
Morador ── "Reserve o salão..." ──▶ Concierge ─▶ reservation_agent ─▶ solicitar_reserva
                                                         │
                         ReservationService: taxa > 0 → REQUIRES_CONFIRMATION (nada gravado)
                                                         │
                               tool_context.request_confirmation(payload={área, data, taxa})
                                                         │
                     ADK emite adk_request_confirmation e pausa a invocation (eventos persistidos)
                                                         │
          AdkRuntime registra PENDING em confirmacoes ─▶ resposta: confirmacoes_pendentes=[{id, acao, detalhes}]

POST /sessoes/{id}/confirmacoes {"id": ..., "confirmado": true}
   → ConfirmationService.claim_pending: UPDATE ... SET PROCESSING WHERE id AND session_id AND status='PENDING'
   → FunctionResponse(id, name="adk_request_confirmation", {"confirmed": true})
   → Runner retoma a invocation; a Tool original roda de novo com tool_context.tool_confirmation
   → create_confirmed_reservation grava (ou recebe "unavailable")
   → confirmação vira APPROVED (ou REJECTED, se confirmado=false)
```

Estados da confirmação (`app/services/confirmation_service.py`): `PENDING → PROCESSING → APPROVED | REJECTED`. `PROCESSING` volta a `PENDING` só quando é certo que nada executou. `APPROVED` registra a **resposta do morador**, não o resultado de negócio: numa disputa, uma confirmação aprovada pode terminar com a Tool devolvendo `unavailable`.

**Confirmação textual não vale.** Mensagens como "eu confirmo" ou "já estou confirmando aqui" chegam ao modelo como texto comum. Só um `FunctionResponse` montado pelo `AdkRuntime` a partir da rota de confirmações preenche `tool_context.tool_confirmation`. Não há Tool nem parâmetro de Tool para aprovar.

Exigem confirmação: reserva de área com taxa > 0 (`salao-de-festas`, `churrasqueira`) e toda autorização de visitante. Não exigem: reserva de área com taxa 0 (`quadra`) e cancelamento de reserva própria.

### Consulta seletiva ao regulamento

```text
Pergunta ─▶ Concierge ─▶ regulation_agent ─▶ consultar_regulamento(pergunta)
         ─▶ RegulationService.search: normalização → tokens → ranking por IDF
            (no máximo 3 trechos e 3000 caracteres; pedidos amplos → query_too_broad)
         ─▶ RegulationRepository: dados/regulamento.md dividido em artigos, em memória
         ─▶ somente os artigos relevantes voltam ao modelo (e aos eventos)
```

Nenhum agente recebe o regulamento nas instruções. A busca é local e determinística (sem embeddings, sem rede, sem LLM).

### Concorrência

A exclusividade "uma reserva ATIVA por área e data" é imposta pelo SQLite no momento da gravação, pelo índice único parcial `uq_reservas_area_data_ativa (area, data) WHERE status = 'ATIVA'`. A consulta de disponibilidade feita antes é só UX. Quando duas aprovações gravam ao mesmo tempo, uma passa e a outra recebe `IntegrityError`, que o Service traduz em `AreaUnavailableError` e a Tool em `{"status": "unavailable"}`: resposta normal `200`, sem erro de servidor.

---

## Garantias (Guarantees)

Os testes citados rodam com `uv run pytest`, sem chave. Usam ADK, FastAPI e SQLite reais e um LLM roteirizado ou hostil. O ensaio integral com Gemini real está em `tests/e2e/test_evaluator_flow.py`; os checkpoints `CP-xx` estão em [docs/ensaio-avaliador.md](docs/ensaio-avaliador.md), com **RUN 1 = PASS e RUN 2 = PASS**.

### 1. Confirmação formal (cobrança ou acesso)

**O que é garantido.** Reserva de área com taxa e autorização de visitante ficam pendentes até uma resposta em `POST /sessoes/{id}/confirmacoes`. Aprovar executa uma única vez; negar não grava nada. Reenviar a resposta de uma confirmação já respondida, usar um `id` inexistente ou um `id` de outra sessão recebe `409` e nada executa. Texto na conversa não confirma.

**Como é aplicado.** A decisão de exigir confirmação vem da taxa gravada no banco (`ReservationService.request_reservation`) ou é incondicional (visitante). A Tool só grava quando o ADK injeta `tool_context.tool_confirmation`:

```python
# app/tools/reservations.py — solicitar_reserva
confirmation = getattr(tool_context, "tool_confirmation", None)
if confirmation is None:
    tool_context.request_confirmation(
        hint="Esta reserva possui cobrança e precisa de confirmação.",
        payload=details,
    )
    return {"status": "pending_confirmation", **details}
if not confirmation.confirmed:
    return {"status": "rejected"}
view = await service.create_confirmed_reservation(apartment, result.area_id, date)
```

A resposta é aceita uma única vez por um `UPDATE` condicional (`rowcount == 1`), antes de qualquer chamada ao Runner:

```python
# app/repositories/confirmation_repository.py — ConfirmationRepository._transition
# (claim: source=PENDING, target=PROCESSING)
result = await self._session.execute(
    update(Confirmacao)
    .where(
        Confirmacao.id == id,
        Confirmacao.session_id == session_id,
        Confirmacao.status == source.value,
    )
    .values(**values)
)
return result.rowcount == 1
```

Inexistente, de outra sessão ou já respondida falham igual (`ConfirmationNotPendingError`), e `app/api/errors.py` traduz para `409`. O modelo não tem como aprovar porque nenhuma Tool recebe `confirmed`, e `create_confirmed_*` não é exposta como Tool.

**Implementação.** `app/tools/reservations.py` (`solicitar_reserva`), `app/tools/visitors.py` (`solicitar_autorizacao_visitante`), `app/runtime/confirmations.py` (`extract_pending_confirmations`, `build_confirmation_response`), `app/runtime/adk_runtime.py` (`AdkRuntime.send_message`, `AdkRuntime.resume_confirmation`), `app/services/confirmation_service.py` (`ConfirmationService.claim_pending`, `mark_approved`, `mark_rejected`), `app/repositories/confirmation_repository.py` (`ConfirmationRepository.claim`), `app/api/confirmacoes.py`.

**Evidência.**
- `tests/api/test_messages_api.py::test_paid_area_creates_one_pending_confirmation_and_no_reservation`, `::test_free_area_is_created_immediately_without_confirmation`, `::test_own_cancellation_needs_no_confirmation_and_keeps_row`
- `tests/api/test_confirmations_api.py::test_approve_creates_reservation_and_replay_is_409`, `::test_reject_resumes_adk_and_creates_nothing`, `::test_unknown_confirmation_id_is_409`, `::test_confirmation_of_another_session_is_409_and_unaffected`
- `tests/adversarial/test_confirmation_attacks.py::test_adv007_textual_confirmation_of_paid_reservation_stays_pending`, `::test_adv009_textual_confirmation_of_visitor_stays_pending`, `::test_adv011_replay_of_approved_id_is_409_and_effect_happens_once`, `::test_adv015_confirmation_from_another_session_is_409_and_does_not_consume`
- `tests/test_tool_schemas.py::test_no_confirmation_parameters_visible_to_model`
- Gemini real: CP-05 a CP-09, CP-11a/b, CP-15c.

### 2. Isolamento por apartamento

**O que é garantido.** O apartamento é fixado na criação da sessão. Nada que o morador escreva faz o assistente ler ou alterar reservas e visitantes de outro apartamento. A consulta de disponibilidade olha a agenda geral da área, mas devolve só `disponivel: true/false`, nunca apartamento, morador ou código.

**Como é aplicado.** As Tools obtêm o apartamento exclusivamente do estado da sessão, sem valor padrão:

```python
# app/tools/context.py — get_session_apartment
state = getattr(tool_context, "state", None)
...
value = state[APARTMENT_STATE_KEY] if present else None   # "apartamento"
```

As consultas pessoais filtram por esse apartamento no SQL. Reserva alheia é indistinguível de inexistente (`ReservationRepository.get_by_apartment_and_code` → `not_found`), e `has_active` só responde existência. `tool_context` é injetado pelo ADK e não aparece no schema visto pelo modelo.

**Implementação.** `app/api/sessoes.py` (`criar_sessao`), `app/runtime/adk_runtime.py` (`AdkRuntime.create_session`, `state={"apartamento": ...}`), `app/tools/context.py` (`get_session_apartment`), `app/tools/reservations.py`, `app/tools/visitors.py`, `app/services/reservation_service.py` (`list_active_reservations`, `cancel_reservation`, `is_available`), `app/repositories/reservation_repository.py` (`get_by_apartment_and_code`, `has_active`).

**Evidência.**
- `tests/api/test_messages_api.py::test_session_101_does_not_get_private_data_of_302`, `::test_cannot_cancel_reservation_of_another_apartment`
- `tests/api/test_sessions_api.py::test_apartment_is_stored_in_session_state`, `::test_apartment_is_immutable_over_http`
- `tests/adversarial/test_identity_attacks.py::test_adv001_simple_false_identity_keeps_session_apartment`, `::test_adv002_tool_context_argument_cannot_replace_state`, `::test_adv004_cancelling_someone_elses_reservation_does_nothing`, `::test_adv005_adv049_third_party_agenda_reveals_only_busy`
- `tests/test_reservation_tools.py::test_availability_does_not_leak_owner`, `tests/test_tool_schemas.py::test_visible_parameters`
- Gemini real: CP-02 (101 dizendo ser o 302), CP-03, CP-10 (data ocupada pelo 302: `RSV-4821` ausente da resposta e dos eventos).

### 3. Persistência no reinício

**O que é garantido.** Depois de parar e subir a API de novo, a mesma sessão devolve os eventos anteriores e aceita novas mensagens. Reservas, cancelamentos e visitantes continuam valendo, os códigos de reserva não se repetem, e uma confirmação pendente criada antes do restart pode ser aprovada depois dele, executando uma única vez.

**Como é aplicado.** Nada de conversa ou domínio vive só em memória: sessões e eventos ficam no `DatabaseSessionService` (`adk_sessions.db`), domínio e confirmações em `condominio.db`. O `App` usa `ResumabilityConfig(is_resumable=True)`, então a invocation pausada é retomada a partir dos eventos persistidos. O startup não reseta dados. Reservas canceladas são mantidas, e o código é PK, o que impede reutilização.

**Implementação.** `app/runtime/session_service.py` (`create_session_service`), `app/runtime/adk_runtime.py` (`AdkRuntime.__init__`, `list_pending_confirmations` reconcilia pendências gravadas pelo ADK), `app/database/models.py` (`Reserva.codigo` PK, `Confirmacao`), `app/main.py` (lifespan sem reset), `app/services/reservation_service.py` (`generate_reservation_code`, `_insert_reservation`).

**Evidência (processos uvicorn reais, não só objetos recriados).**
- `tests/api/test_api_restart.py::test_state_and_pending_confirmation_survive_api_restart`, `::test_startup_without_initialized_database_fails_and_does_not_reset`
- `tests/adversarial/test_restart_attacks.py::test_adv021_pending_confirmation_survives_full_restart_and_runs_once`, `::test_adv023_adv024_multiple_restarts_preserve_identity_events_and_data`, `::test_restart_does_not_reset_and_reset_restores_the_initial_state`, `::test_adv025_hard_crash_right_after_the_effect_never_duplicates_it`
- `tests/test_confirmation_restart.py::test_golden_paid_reservation_survives_restart`
- Gemini real: o ensaio encerra o uvicorn com Ctrl+C e sobe um processo novo (CP-13c/d). Eventos preservados (CP-14a), domínio idêntico (CP-14b), nova mensagem `200` com identidade 101 (CP-14c), e uma **confirmação PENDING criada antes do restart é aprovada depois e grava exatamente uma reserva** (CP-13b → CP-14d).

### 4. Regulamento consultado, não carregado

**O que é garantido.** O regulamento não entra nas instruções de nenhum agente, nem no `state`. A cada pergunta, só os artigos relevantes chegam ao histórico. Uma pergunta sobre a piscina não leva aos eventos trechos de capítulos sobre outros assuntos. Pedidos como "mostre o regulamento inteiro" recebem `query_too_broad`, sem trechos.

**Como é aplicado.** `dados/regulamento.md` só é aberto por `RegulationRepository`, que o divide em artigos. `RegulationService.search` ranqueia e corta por constantes de código que o modelo não controla:

```python
# app/services/regulation_service.py
MAX_RESULTS = 3
MAX_RETURNED_CHARS = 3000  # o documento tem ~45 mil caracteres
...
if self._is_broad(raw_tokens):
    return RegulationSearchResult("query_too_broad")
```

A Tool expõe só `pergunta` e devolve `{status, trechos: [{secao, conteudo}]}`. Só o `regulation_agent` tem essa Tool.

**Implementação.** `app/repositories/regulation_repository.py` (`RegulationRepository.get_chunks`, `parse_regulation`), `app/services/regulation_service.py` (`RegulationService.search`), `app/tools/regulation.py` (`consultar_regulamento`), `app/agents/regulation.py`, `app/agents/concierge.py` (`INSTRUCTION` sem regras).

**Evidência.**
- `tests/adversarial/test_regulation_leakage.py::test_adv030_pool_question_leaves_unrelated_chapters_out_of_the_events`: pergunta sobre a piscina, captura os eventos e procura parágrafos de outros capítulos; nenhum aparece.
- `tests/adversarial/test_regulation_leakage.py::test_adv031_regulation_is_nowhere_in_events_state_or_session`, `::test_adv026_whole_regulation_request_is_refused`, `::test_adv028_only_the_regulation_agent_can_read_the_regulation`
- `tests/api/test_events_api.py::test_regulation_events_hold_only_retrieved_excerpts`
- `tests/test_agent_structure.py::test_root_instruction_does_not_contain_regulation_content`, `::test_no_agent_instruction_contains_any_regulation_text`
- Gemini real: CP-12a (horário do Art. 22 citado), CP-12b (transferência para `regulation_agent` + `consultar_regulamento`), CP-12c (trechos sobre garagem e documento ausentes dos eventos; 918 de 43 024 caracteres retornados).

### 5. Reserva concorrente segura

**O que é garantido.** Para uma mesma área e data existe no máximo uma reserva `ATIVA`, mesmo com duas aprovações simultâneas. As duas respostas HTTP são `200`: uma com a reserva criada, a outra com indisponibilidade como resultado de negócio.

**Como é aplicado.** Pelo banco, no instante da gravação:

```python
# app/database/models.py — Reserva.__table_args__
Index(
    "uq_reservas_area_data_ativa",
    "area",
    "data",
    unique=True,
    sqlite_where=text("status = 'ATIVA'"),
),
```

`ReservationService._insert_reservation` grava em transação própria. A violação desse índice específico, identificada pelo código SQLite e pelas colunas, vira `AreaUnavailableError`; colisão de código gera um código novo. A Tool devolve `{"status": "unavailable"}` sem dados da reserva vencedora. O SQLite usa WAL e `busy_timeout=5000` (`app/database/connection.py`), mas a exclusividade vem do índice, não da espera nem do `SELECT` prévio.

**Implementação.** `app/database/models.py` (`uq_reservas_area_data_ativa`), `app/repositories/reservation_repository.py` (`ReservationRepository.insert`), `app/services/reservation_service.py` (`_insert_reservation`), `app/services/_persistence.py` (`is_unique_violation`), `app/tools/reservations.py` (`AreaUnavailableError` → `unavailable`).

**Evidência.**
- `tests/test_reservation_concurrency.py::test_database_rejects_two_active_even_bypassing_service`, `::test_concurrency_does_not_depend_on_availability_check`, `::test_repeated_concurrency_race`
- `tests/test_concurrent_confirmations.py::test_two_sessions_approve_concurrently_one_reservation`
- `tests/api/test_concurrency_api.py::test_concurrent_http_approvals_leave_exactly_one_active_reservation`
- `tests/adversarial/test_concurrency_attacks.py::test_adv033_to_036_two_sessions_race_200_200_one_active_reservation`, `::test_adv037_stress_ten_sessions_one_winner_nine_unavailable`, `::test_adv034_035_037_038_real_server_http_race`
- Gemini real: S3 (101) e S4 (201) aprovam o salão em 2030-05-11 ao mesmo tempo → `200`/`200`, resultados `created`/`unavailable`, exatamente 1 reserva ativa (CP-16a–c).

### Resumo

| Garantia | Mecanismo principal | Evidência |
|---|---|---|
| Confirmação formal | Tool Confirmation do ADK + claim atômico `PENDING → PROCESSING` + `409` | `test_confirmation_attacks.py`, `test_confirmations_api.py`, CP-05–09, CP-11 |
| Isolamento por apartamento | `state["apartamento"]` gravado na criação, lido via `ToolContext`; SQL filtrado | `test_identity_attacks.py`, `test_messages_api.py`, CP-02, CP-03, CP-10 |
| Persistência no reinício | `DatabaseSessionService` + SQLite de domínio + confirmações persistidas + resumability | `test_restart_attacks.py`, `test_api_restart.py`, CP-13–14 |
| Regulamento seletivo | `RegulationService.search` com limites fixos; só o `regulation_agent` tem a Tool | `test_regulation_leakage.py`, `test_agent_structure.py`, CP-12 |
| Reserva concorrente | Índice único parcial `uq_reservas_area_data_ativa` | `test_reservation_concurrency.py`, `test_concurrency_attacks.py`, CP-16 |

Limitações conhecidas: uma confirmação pode ficar em `PROCESSING` se o processo cair no meio da retomada (seguro contra duplicação, sem reconciliação automática), e a API devolve 500 se a cota do Gemini se esgotar após os retries. Ver [riscos técnicos](docs/riscos-tecnicos.md).

---

## Como rodar (How to run)

### Pré-requisitos

- Python **3.12** (`.python-version`; `pyproject.toml` exige `>=3.12,<3.13`). O `uv` instala a versão se faltar.
- [uv](https://docs.astral.sh/uv/) (validado com 0.12.23).
- Chave do **Google AI Studio** com cota para algumas dezenas de chamadas por fluxo. O free tier observado (5 req/min, 20 req/dia) não comporta o fluxo completo do avaliador.

Nenhum serviço externo é necessário: o armazenamento é SQLite local.

### Instalação

```bash
uv sync
```

Instala as versões travadas em `uv.lock`, entre elas `google-adk[db]==2.9.1`, FastAPI, Uvicorn, SQLAlchemy 2.1 e aiosqlite.

### Variáveis de ambiente

Copie o modelo e preencha a chave.

```bash
cp .env.example .env
```

No PowerShell:

```powershell
Copy-Item .env.example .env
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GOOGLE_API_KEY` | sim | Chave do Google AI Studio. |
| `GEMINI_MODEL` | sim | Modelo usado pelos quatro agentes. Não há default no código (`app/config.py`). Validado com `gemini-3.6-flash`. |
| `GOOGLE_GENAI_USE_VERTEXAI` | não | `FALSE` (padrão): usa o AI Studio, não o Vertex AI. |
| `DOMAIN_DATABASE_URL` | não | Padrão `sqlite+aiosqlite:///./data/condominio.db`. Caminhos relativos são resolvidos a partir da raiz do projeto. |
| `ADK_SESSION_DATABASE_URL` | não | Padrão `sqlite+aiosqlite:///./data/adk_sessions.db`. |

O `.env` está no `.gitignore`. As variáveis são lidas por `app/config.py` (`Settings`), que também repassa a chave ao `google-genai`.

### Restaurar os dados iniciais

```bash
uv run python -m scripts.reset
```

Recria `data/condominio.db` a partir de `dados/` (6 apartamentos, 3 áreas, 3 reservas, 2 visitantes, nenhuma confirmação) e apaga `data/adk_sessions.db`. Use `--keep-sessions` para preservar as sessões. `dados/` é só lido.

Rode o reset **antes da primeira subida**: a API não reseta nada sozinha e não sobe com o banco vazio.

### Subir a API

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

A API responde em `http://localhost:8000`, e o Swagger fica em `http://localhost:8000/docs`. Para reiniciar, pare com Ctrl+C e rode o mesmo comando, sem reset: sessões, eventos e dados continuam.

### Rotas

Todas recebem e devolvem JSON. Rotas com `{session_id}` respondem `404` para sessão inexistente.

| Método | Rota | Sucesso | Observações |
|---|---|---|---|
| `POST` | `/sessoes` | `201 {"session_id"}` | corpo `{"apartamento": "101"}`; `404` se o apartamento não existe |
| `POST` | `/sessoes/{session_id}/mensagens` | `200 {"resposta", "confirmacoes_pendentes"}` | corpo `{"texto": "..."}` |
| `POST` | `/sessoes/{session_id}/confirmacoes` | `200`, mesmo formato de mensagens | corpo `{"id": "...", "confirmado": true}`; `409` se não há confirmação pendente com esse `id` nesta sessão |
| `GET` | `/sessoes/{session_id}/eventos` | `200 [evento, ...]` | eventos ADK completos, em ordem |
| `GET` | `/apartamentos/{apartamento}/reservas` | `200 [{"codigo", "area", "data"}]` | verificação: reservas ativas, lidas direto do banco |
| `GET` | `/apartamentos/{apartamento}/visitantes` | `200 [{"nome", "data"}]` | verificação: lidas direto do banco |

`confirmacoes_pendentes` lista todas as confirmações `PENDING` da sessão no momento da resposta, e vem vazia quando não há nenhuma. `resposta` pode ser `""` quando a execução parou esperando confirmação. Exemplo real de uma reserva paga:

```json
{
  "resposta": "",
  "confirmacoes_pendentes": [
    {
      "id": "adk-aa8568c0-6571-4ec2-b2ad-08183b040ec6",
      "acao": "reservar_area",
      "detalhes": {"area": "churrasqueira", "data": "2030-04-20", "taxa_centavos": 8000}
    }
  ]
}
```

`acao` é `reservar_area` (`detalhes`: `area`, `data`, `taxa_centavos`) ou `autorizar_visitante` (`detalhes`: `nome`, `data`).

### Exemplos

Os comandos abaixo usam `curl` em bash (Linux, macOS, Git Bash ou WSL). No Git Bash do Windows, prefira textos sem acento no `-d`, ou escape os acentos em JSON (`salão`).

Criar sessão:

```bash
curl -X POST http://localhost:8000/sessoes \
  -H "Content-Type: application/json" \
  -d '{"apartamento":"101"}'
```

O mesmo pelo PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/sessoes -ContentType "application/json" -Body '{"apartamento":"101"}'
```

Reserva gratuita (quadra), criada sem confirmação:

```bash
curl -X POST http://localhost:8000/sessoes/<SESSION_ID>/mensagens \
  -H "Content-Type: application/json" \
  -d '{"texto":"Reserve a quadra para 2030-04-06."}'
```

Reserva paga (churrasqueira), que devolve uma confirmação pendente:

```bash
curl -X POST http://localhost:8000/sessoes/<SESSION_ID>/mensagens \
  -H "Content-Type: application/json" \
  -d '{"texto":"Reserve a churrasqueira para 2030-04-20."}'
```

Aprovar a confirmação (use `false` para negar). Reenviar o mesmo `id` responde `409`.

```bash
curl -X POST http://localhost:8000/sessoes/<SESSION_ID>/confirmacoes \
  -H "Content-Type: application/json" \
  -d '{"id":"<CONFIRMATION_ID>","confirmado":true}'
```

Conferir efeitos e eventos:

```bash
curl http://localhost:8000/apartamentos/101/reservas
```

```bash
curl http://localhost:8000/sessoes/<SESSION_ID>/eventos
```

### Testes

Suíte padrão, sem rede e sem chave (bancos temporários, LLM roteirizado ou hostil; não toca em `data/`):

```bash
uv run pytest
```

Resultado da entrega: `486 passed, 35 deselected`. Os testes deselecionados têm o marcador `integration` e usam Gemini real. Sem `GOOGLE_API_KEY` e `GEMINI_MODEL` eles são pulados.

Integrações com Gemini real (`tests/integration/`, `tests/adversarial/test_live_gemini.py` e o ensaio E2E):

```bash
uv run pytest -m integration -v
```

Ensaio integral do fluxo do avaliador:

```bash
uv run pytest tests/e2e/test_evaluator_flow.py -m integration -v -s
```

O ensaio gerencia o próprio servidor: roda `scripts.reset` sobre `data/`, sobe o uvicorn em `127.0.0.1:8000`, percorre o fluxo, reinicia o processo com Ctrl+C e termina com aprovações simultâneas. Antes de rodá-lo, **pare qualquer API em execução** (a porta 8000 precisa estar livre) e lembre que ele **reseta os dados locais**. A evidência resumida fica em `data/e2e_evidence_<label>.json`, ignorado pelo Git.
