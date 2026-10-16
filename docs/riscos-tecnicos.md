# Riscos técnicos — Residencial Aurora

> **Estado final (Passo 13, 16/10/2026):** implementação concluída e congelada. As cinco garantias estão implementadas e cobertas por testes offline (`uv run pytest`: 486 passed, 35 deselected) e pelo ensaio integral do avaliador com **Gemini real, uvicorn real e restart real** (RUN 1 = PASS, RUN 2 = PASS; [ensaio-avaliador.md](ensaio-avaliador.md)). O [README](../README.md) é a descrição autoritativa do sistema final; as seções datadas deste documento são registro histórico, e menções a "Gemini pendente" nelas descrevem o estado anterior ao Passo 12.
> "Como validar" descreve o plano completo; verificações já executadas estão identificadas nas evidências e em [garantias.md](garantias.md#estado-atual-e-evidências). Arquivo existente não implica funcionalidade implementada.

Documentos relacionados: [`garantias.md`](garantias.md) · [`decisoes-arquiteturais.md`](decisoes-arquiteturais.md)

## Convenção

- **Status:** `Aberto` (sem validação suficiente), `Em validação` (evidência parcial), `Mitigado` ou `Aceito`. Uma evidência de persistência, Service ou Tool isolada não encerra o risco ponta a ponta. Os cenários e endpoints descritos são requisitos do fluxo futuro quando não marcados como implementados.
- **Impacto:** Alto / Médio / Baixo.

## Resumo

Status final (Passo 13): `VALIDADO` = coberto por testes e pelo ensaio E2E com Gemini real; `MITIGADO` = proteção implementada com risco residual conhecido; `ABERTO` = sem mitigação completa.

| ID | Risco | Impacto | Garantia afetada | Status final |
|---|---|---|---|---|
| [RT-001](#rt-001--tool-confirmation--sessão-persistente) | Tool Confirmation + sessão persistente | **Alto** | 1, 3 | **VALIDADO** (offline, HTTP e Gemini real com restart: CP-13b/CP-14d). Residual: `PROCESSING` órfão |
| [RT-002](#rt-002--retomada-da-confirmação-no-agente-errado) | Retomada da confirmação no agente errado | **Alto** | 1 | **VALIDADO** (offline e Gemini real) |
| [RT-003](#rt-003--concorrência-de-reservas) | Concorrência de reservas | **Alto** | 5 | **VALIDADO** (domínio, runtime, HTTP e Gemini real: CP-16a–c) |
| [RT-004](#rt-004--vazamento-de-identidade-entre-apartamentos) | Vazamento de identidade entre apartamentos | **Alto** | 2 | **VALIDADO** (offline e Gemini real: CP-02, CP-03, CP-10) |
| [RT-005](#rt-005--excesso-de-conteúdo-do-regulamento-nos-eventos) | Excesso de conteúdo do regulamento nos eventos | Médio | 4 | **VALIDADO** (offline e Gemini real: CP-12c). Residual: busca lexical |
| [RT-006](#rt-006--reutilização-de-confirmation-id) | Reutilização de confirmation ID | **Alto** | 1 | **VALIDADO** (`409` offline e Gemini real: CP-08, CP-09, CP-15c) |
| [RT-007](#rt-007--custo-e-disponibilidade-em-laços-do-modelo) | Custo e disponibilidade em laços do modelo | Médio | — | **MITIGADO** (teto de 25 chamadas por execução) |
| [RT-008](#rt-008--serialização-de-entrada-inválida-na-resposta-de-erro) | Serialização de entrada inválida | Baixo | — | **MITIGADO** |
| [RT-009](#rt-009--evidência-instável-de-restart-e-ordem-dos-eventos) | Evidência instável de restart | Baixo | 3 | **MITIGADO** |
| [RT-010](#rt-010--cota-e-indisponibilidade-do-gemini) | Cota e indisponibilidade do Gemini | Médio | — | **ABERTO** (retry com backoff; esgotado, a API devolve 500) |
| — | `PROCESSING` órfão após queda no meio da retomada (RT-001, RT-006) | Médio | 1 | **ABERTO** (seguro contra duplicação; sem reconciliação automática) |

**Prioridade atual:** manter a suíte offline verde e repetir o ensaio E2E a cada mudança de ADK, modelo ou topologia. Os itens `ABERTO` acima são limitações aceitas para a entrega.

---

## RT-001 — Tool Confirmation + sessão persistente

### Status
**Mitigado / validado na versão atual (Google ADK 2.9.1) com LLM roteirizado — Passo 8.** Exercitado via HTTP nos Passos 10–11; ainda **não** exercitado com Gemini real. Histórico (Passo 7), dividido em:

| Parte | Situação |
|---|---|
| Tool Confirmation em sessão compatível (`InMemorySessionService`, Runner real, ADK 2.9.1) | **Validado** com LLM roteirizado (`tests/test_tool_confirmation_scripted.py`): pausa, `FunctionResponse` formal, retomada, aprovação grava uma vez, rejeição não grava. Com Gemini real: testes escritos em `tests/integration/test_tool_confirmation.py`, **não executados** onde não havia chave. |
| Tool Confirmation + `DatabaseSessionService` + SQLite + restart | **Validado no Passo 8 (ADK 2.9.1, `ResumabilityConfig(is_resumable=True)`)**: pendência criada no processo A, runtime reconstruído por completo em processo separado, aprovação/rejeição retomam a invocation correta e a Tool original executa (ou é rejeitada) uma única vez; reenvio falha com `ConfirmationNotPendingError`. Testes: `tests/test_confirmation_restart.py` (subprocessos), `tests/test_persistent_confirmation.py`, `tests/test_concurrent_confirmations.py`. Arquivos: `app/runtime/adk_runtime.py`, `app/services/confirmation_service.py`, `app/repositories/confirmation_repository.py`. Só o **modelo** é falso nesses testes. |

**Riscos residuais do RT-001:** (1) Gemini real: `tests/integration/test_persistent_confirmation_gemini.py` existe e é pulado sem `GOOGLE_API_KEY`/`GEMINI_MODEL`; (2) a resumability do ADK é *at-least-once* e `ResumabilityConfig` é experimental — qualquer atualização do ADK exige reexecutar os testes acima; (3) queda do processo **durante** a retomada deixa a confirmação em `PROCESSING` (seguro contra duplicação, porém sem reconciliação automática: requer verificação manual do efeito no domínio); (4) não há transação única entre `adk_sessions.db` e `condominio.db` — a reconciliação cobre apenas o caso "ADK gravou, tabela não".

**Evidência histórica parcial (Passo 2, superada pelos testes do Passo 8):** `DatabaseSessionService` + SQLite persistiu sessão, `state` e evento mínimo entre processos distintos. Naquele marco não havia validação de Tool Confirmation com Runner; os testes do Passo 8 descritos acima agora cobrem esse fluxo offline.

### Impacto
**Alto.** Se a retomada não funcionar com sessão persistida, as Garantias 1 e 3 ficam comprometidas ao mesmo tempo.

**Probabilidade:** relevante até validação prática. Não é possível estimá-la sem testar.

### Descrição
O Tool Confirmation do Google ADK pausa a execução de uma tool e depende de uma resposta do cliente para retomar. A retomada pode depender de:

- do agente que originalmente pediu a confirmação;
- da topologia dos agentes;
- do Runner;
- da configuração do App;
- do serviço de sessão persistente.

**Motivo do risco:** a documentação do ADK indica que alguns serviços de sessão podem não ser suportados para confirmação, e o comportamento pode variar conforme a configuração e a versão. Uma combinação que funciona com sessão em memória **pode falhar** com sessão persistida em SQLite. Além disso, o fluxo previsto (API própria com resposta via endpoint HTTP) vai além do cenário típico de desenvolvimento do ADK.

### Cenário de falha
1. O morador pede uma reserva com taxa; surge uma confirmação pendente.
2. O morador aprova via `POST /confirmacoes`; a API responde `200` sem erro.
3. A execução **não é retomada** (ou é retomada no agente errado) e a reserva **nunca é gravada**; o modelo pode, inclusive, dizer que "foi feito".

É uma **falha silenciosa**: nenhum erro, nenhuma ação.

Variante de reinício: a confirmação é criada, a API é reiniciada e a aprovação depois do reinício não retoma a execução.

### Mitigação e validação restante
- Isolar toda a integração em `AdkRuntime` ([ADR-010](decisoes-arquiteturais.md#adr-010--isolamento-da-integração-adk-em-adkruntime)).
- Manter controle próprio de confirmações ([ADR-012](decisoes-arquiteturais.md#adr-012--controle-próprio-de-confirmações-além-do-estado-do-adk)) com `invocation_id` e `agent_name`.
- **Nunca** reportar sucesso ao morador sem verificar que a ação executou (o resultado vem da tool/serviço, não do texto do modelo).
- Validar com **sessão persistida desde o primeiro teste**, não só em memória.
- Fixar a **versão exata** do ADK e reexecutar a validação em qualquer atualização.

### Como validar
> O protótipo tornou-se o AdkRuntime e já cobre os itens abaixo offline; repetir com Gemini; HTTP roteirizado já coberto:

1. aprovar → a ação executa **uma vez**;
2. negar → nada executa;
3. aprovar **depois de reiniciar a API** → a ação executa;
4. reenviar a aprovação → `409`, sem nova execução;
5. o resultado da tool é visível nos eventos da sessão.

**Prioridade atual:** validar com Gemini real; HTTP roteirizado já está coberto. A topologia foi mantida após os testes offline do Passo 8 (ADR-002).

---

## RT-002 — Retomada da confirmação no agente errado

### Status
**Validado na versão atual com LLM roteirizado** — Passo 7 (InMemory) e **Passo 8**: com `DatabaseSessionService`, resumability e restart real, a resposta formal retomou a Tool no agente que a pediu (`reservation_agent` / `visitor_agent`, conferido em `agent_name`, eventos e efeito no banco) e duas confirmações independentes simultâneas (sessões diferentes) foram retomadas sem interferência. Topologia mantida. Pendente: Gemini real. Duas confirmações na mesma sessão e fora de ordem têm cobertura em `tests/adversarial/test_confirmation_attacks.py`.

### Impacto
**Alto.** Afeta diretamente a Garantia 1 e a escolha da topologia de agentes.

### Descrição
Com Concierge e especialistas, a pausa pode acontecer **dentro** de um especialista. A resposta do morador precisa chegar **ao agente que pediu** a confirmação; quem escolhe o agente que recebe a retomada é o Runner, e essa escolha pode variar conforme a topologia, as regras de transferência entre agentes, a configuração de retomada do App e o serviço de sessão.

### Cenário de falha
1. O Reservas Agent pede confirmação.
2. O morador aprova; o Runner entrega a resposta ao Concierge (ou a outro agente).
3. O agente que recebe não possui a chamada pendente: a retomada não ocorre e nada é executado — sem erro visível.

Também: duas confirmações pendentes na mesma sessão (por exemplo, reserva e visitante) sendo retomadas no agente trocado.

### Mitigação e validação restante
- Registrar `agent_name` e `invocation_id` na tabela de confirmações.
- Concentrar a lógica de retomada em `AdkRuntime.resume_confirmation()`.
- Testar a escolha inicial `sub_agents` + transferência (ADR-002) e só revisá-la com base no resultado observado.
- Testar com **cada** especialista que pode pedir confirmação (Reservas e Visitantes).

### Como validar
> **Planejado:**

1. Para Reservas e para Visitantes, pedir a ação, aprovar e verificar que a execução ocorre **no agente certo** (conferindo eventos e efeito de negócio).
2. Repetir com sessão persistida e depois de reiniciar a API.
3. Testar duas confirmações pendentes simultâneas na mesma sessão.
4. Testar nova mensagem enviada enquanto há confirmação pendente: nada deve executar sem confirmação.

**Momento recomendado:** junto com o RT-001.

---

## RT-003 — Concorrência de reservas

### Status
**Mitigado no domínio** (Passo 4, 11/10/2026) — `tests/test_reservation_concurrency.py` comprova, sobre Service → Repository → SQLite temporário com sessões independentes, 1 sucesso + 1 `AreaUnavailableError` + 1 reserva ATIVA (101 × 201, salão, 2030-05-11), 25 repetições sem duplicidade, rollback seguido de nova operação, liberação após cancelamento e unicidade de código sob concorrência. **Não encerrado:** confirmações concorrentes já foram validadas no AdkRuntime (`test_two_sessions_approve_concurrently_one_reservation`); a camada HTTP também tem cobertura nos Passos 10–11. Contenção prolongada no domínio foi corrigida e coberta por regressões (abaixo).

**Evidência histórica anterior (Passos 2 e 3, 11/10/2026; não descreve toda a suíte atual):** `scripts.check_constraints` passou em banco temporário, incluindo o índice único parcial `uq_reservas_area_data_ativa`. O teste `test_concurrent_creation_single_winner` verifica um sucesso, um `AreaUnavailableError` e uma única reserva ATIVA persistida para 101 × 201 no salão em 2030-05-11. O teste `test_concurrent_many_single_winner`, com seis apartamentos, verifica um sucesso e cinco erros de domínio, mas não conta o estado final. Mensagens sem dados de terceiros são verificadas em testes separados de data ocupada e cancelamento alheio, não nos testes concorrentes.

**Falha histórica (corrigida nesta revisão):** em banco temporário, manter `BEGIN IMMEDIATE` em outra conexão além de `busy_timeout=5000` fazia criar reserva, cancelar reserva e autorizar visitante propagarem `sqlalchemy.exc.OperationalError` (`database is locked`). A regressão agora está em `tests/test_persistence_failures.py`: o domínio devolve `StorageBusyError`, sem efeito parcial, e aceita nova operação após liberar o bloqueio.

**Correção implementada:** `app/services/_persistence.py` traduz apenas `SQLITE_BUSY`/`SQLITE_LOCKED` (incluindo códigos estendidos), após encerrar a sessão; as seis tools devolvem `temporarily_unavailable`, sem SQL. Mantém-se `busy_timeout=5000`, sem retry automático; banco ocupado não significa área ocupada. O ADK já foi exercitado em `tests/test_concurrent_confirmations.py`; duas respostas HTTP `200` têm cobertura nos Passos 10–11.

### Impacto
**Alto.** Dupla reserva viola a regra de negócio mais sensível a concorrência (Garantia 5).

### Descrição
Duas aprovações simultâneas para a mesma área e data podem passar por uma verificação de disponibilidade ao mesmo tempo. A exclusividade precisa valer **no instante da gravação** (constraint + transação). Há também riscos específicos de SQLite: um único escritor por vez, possibilidade de erro de banco ocupado e comportamento sob execução assíncrona.

### Cenário de falha
- Duas reservas ativas da mesma área e data (se a constraint estiver ausente, mal definida ou valer também para canceladas/ativas de forma incorreta).
- A perdedora recebe erro de servidor (`500`) por exceção de violação de unicidade ou de "database is locked" não tratada.
- A perdedora revela o código ou o apartamento da vencedora.
- A constraint bloqueia indevidamente nova reserva depois de um cancelamento.

### Mitigação implementada no domínio; integração pendente
- Constraint de unicidade para reservas **ativas** + transação ([ADR-008](decisoes-arquiteturais.md#adr-008--integridade-concorrente-garantida-pelo-banco)).
- Conflito tratado como resultado normal no service.
- Política implementada: WAL, `busy_timeout=5000`, sessões independentes e `StorageBusyError`, sem retry automático de contenção. A unicidade depende do índice.
- Respostas sem dados do outro apartamento (RT-004).

### Como validar
> **Planejado:**

1. ~~Teste direto na camada de dados com várias gravações concorrentes (sem modelo).~~ **Feito no Passo 4** (`tests/test_reservation_concurrency.py`).
2. Fluxo ponta a ponta: duas sessões (101 e 201) aprovam a mesma área/data **ao mesmo tempo**; esperado: duas respostas `200` e **exatamente uma** reserva ativa.
3. Cancelar e reservar de novo a mesma área/data → já coberto no Service; ainda validar pelo fluxo completo.
4. ~~Repetir várias vezes (a condição de corrida é intermitente).~~ **Feito no Passo 4** no nível de domínio (25 iterações); repetir também no fluxo via API.
5. **Feito nesta revisão:** regressões de lock real em criação, cancelamento e autorização de visitante, incluindo tools de escrita: erro seguro, nenhum efeito parcial e nova operação após liberar o lock.

**Momento recomendado:** assim que o esquema de reservas e a gravação existirem.

---

## RT-004 — Vazamento de identidade entre apartamentos

### Status
**Mitigado em Services, Tools e cenários roteirizados com Runner; HTTP coberto; Gemini pendente.** Os testes dos Passos 3 e 5 comprovam filtros por apartamento, disponibilidade booleana, cancelamento alheio neutro e ausência de identidade no schema. As tools obtêm o apartamento exclusivamente de `tool_context.state`, sem fallback. Evidências: `tests/test_reservation_tools.py`, `tests/test_visitor_tools.py` e `tests/test_tool_schemas.py`.

**Limite:** os testes isolados do Passo 5 usam contexto simulado; desde o Passo 6 há conversa com Agent/Runner real (`tests/test_agent_runtime_scripted.py`) e o Passo 9 inspeciona eventos reais serializados. Isso não comprova comportamento do Gemini. A API cria a sessão e valida o apartamento desde o Passo 10. O helper não autentica moradores; autenticação permanece fora de escopo. Disponibilidade valida presença/formato da identidade, mas não a existência do apartamento no cadastro.

### Impacto
**Alto.** Quebra a Garantia 2; envolve dados de outros moradores.

### Descrição
Mesmo com a identidade vinda da sessão, dados de outros apartamentos podem vazar por **saídas** das tools: mensagens de erro, resultados de consulta, resposta de conflito. Tudo que uma tool devolve entra na conversa **e nos eventos persistidos**, que a API expõe por completo (`GET /sessoes/{id}/eventos`).

### Cenário de falha
- Uma tool aceita `apartamento` como parâmetro e o modelo o preenche com outro valor.
- Cancelar reserva de terceiros devolve "reserva RSV-xxxx pertence ao apto 302".
- Reservar uma data ocupada devolve quem ocupa a data.
- Um serviço de consulta usa filtro por apartamento incompleto.
- Dados de terceiros ficam nos eventos mesmo que o modelo não os repita ao morador.

### Mitigação implementada nas tools; integração pendente
- Nenhuma tool com apartamento escolhido pelo modelo ([ADR-007](decisoes-arquiteturais.md#adr-007--identidade-obtida-exclusivamente-da-sessão)).
- Consultas e alterações de dados pessoais usadas pelas tools são escopadas por apartamento; disponibilidade é global e retorna apenas booleano. Consultas administrativas/globais de infraestrutura não são tools públicas.
- Consulta de disponibilidade devolve só "livre/ocupada".
- Respostas indistinguíveis para "não existe" e "é de outro apartamento".
- Revisão de código a cada nova tool, com checklist: parâmetros, retorno, mensagens de erro.

### Como validar
> **Planejado:**

1. Em sessão do 101, pedir dados e cancelamento do 302, dizendo ser do 302.
2. Tentar reservar data ocupada pelo 302.
3. Buscar nos eventos da sessão por códigos, nomes e números de apartamento de terceiros.
4. **Feito no Passo 5:** inspeção dos schemas gerados pelo ADK para as seis tools, com parâmetros esperados e nomes privilegiados proibidos. Revalidar ao registrar tools nos agentes.

**Momento recomendado:** contínuo, desde a primeira tool.

---

## RT-005 — Excesso de conteúdo do regulamento nos eventos

### Status
**Mitigado (Passo 9)** — comprovado por testes offline com ADK real e LLM roteirizado; validação com Gemini real pendente (testes `integration` pulados sem chave).

### Impacto
Médio. Compromete a Garantia 4 (custo e conteúdo dos eventos); não expõe dados de moradores.

### Descrição
O retorno da tool de regulamento fica registrado nos eventos e acompanha o histórico seguinte. Se a seleção do trecho for ampla, assuntos sem relação entram no histórico.

### Cenário de falha
- A tool devolve um capítulo grande (ou o arquivo todo) para uma pergunta pontual.
- O trecho devolvido mistura assuntos de outros capítulos.
- O agente principal ou algum especialista recebe o texto nas instruções por engano.
- Pergunta ambígua faz a seleção devolver trechos demais ou de assuntos errados.

### Mitigação implementada
- Retorno por artigo (menor que o capítulo), no máximo 3 trechos e 3000 caracteres de conteúdo somado, fixados em código. O teto inclui o primeiro trecho; unidades indivisíveis maiores são descartadas sem truncamento (`test_oversized_atomic_paragraph_never_exceeds_budget`).
- `query_too_broad` para pedidos de "tudo"/"inteiro" e `not_found` quando a cobertura dos termos é insuficiente — nunca fallback para o texto completo.
- Instruções e `session.state` sem regulamento; Concierge sem a Tool.

### Evidências
- `test_regulation_events_do_not_include_unrelated_sections`: serializa eventos e sessão e verifica que nenhum parágrafo de capítulo não relacionado (nem o documento completo) aparece; `test_tool_does_not_return_the_whole_document`; `test_broad_query_through_agents_never_returns_document`; `test_session_state_never_holds_regulation`; `test_no_agent_instruction_contains_any_regulation_text`.

### Risco residual
- Busca lexical: sinônimos fora do texto geram `not_found` (falso negativo seguro); um artigo relacionado pode ficar de fora se o vocabulário não coincidir.
- Dois ou três artigos do mesmo capítulo podem aparecer juntos (por desenho) e ficam nos eventos.
- Comportamento do Gemini (roteamento, fidelidade da redação, não alucinar em `not_found`) só é verificável com `uv run pytest -m integration` e chave válida.

---

## RT-006 — Reutilização de confirmation ID

### Status
**Mitigado no AdkRuntime (Passo 8) e HTTP (Passos 10–11).** O ADK isolado reexecuta a Tool e pode duplicar visitante (descoberta preservada em `test_finding_reused_visitor_confirmation_id`). O runtime barra reenvios, IDs desconhecidos e de outra sessão com `ConfirmationNotPendingError`, antes do Runner. Evidências: `tests/test_persistent_confirmation.py`, `tests/test_confirmation_service.py`, `tests/test_concurrent_confirmations.py` e `tests/test_confirmation_restart.py`. A API traduz o erro para 409.

### Impacto
**Alto.** Pode causar execução duplicada de ação com cobrança ou liberação de acesso.

### Descrição
Uma confirmação já respondida (aprovada ou negada) não deve poder ser usada de novo. Reuso pode ocorrer por reenvio do cliente, repetição de requisição, `id` de outra sessão ou duas respostas simultâneas à mesma confirmação.

### Cenário de falha
- O mesmo `id` aprovado duas vezes executa a ação duas vezes.
- Um `id` de outra sessão é aceito.
- Duas requisições simultâneas passam pela checagem de `PENDING` antes de a primeira atualizar o estado.
- Um `id` negado depois é aprovado.

### Mitigação e validação restante
- Somente `PENDING` **da sessão** aceita resposta; caso contrário, `ConfirmationNotPendingError` (HTTP 409).
- Claim **implementado e atômico** `PENDING → PROCESSING`, condicionado à sessão/ID/estado, seguido de `APPROVED/REJECTED` após resposta da Tool.
- A execução ocorre somente para quem vence a transição.
- Constraints de integridade nos dados de negócio como segunda barreira (por exemplo, unicidade da reserva).

### Como validar
> **Planejado:**

1. Reenviar a mesma resposta (mesmo `id`) → `409`; reserva/visitante continua uma só.
2. Responder `id` inexistente → `409`.
3. Responder `id` de outra sessão → `409`.
4. Tentar aprovar confirmação negada → `409`.
5. Aprovações simultâneas do mesmo `id` (o comportamento exato é livre no contrato, mas **não** pode haver efeito duplicado).

**Momento recomendado:** junto com o endpoint de confirmações.

---

## Observações do Passo 6

- *(Histórico do Passo 6; ver RT-001/RT-002 acima para o estado após o Passo 8.)* RT-001 e RT-002 estavam abertos: Tool Confirmation real e retomada ainda não haviam sido implementadas. A transferência Concierge → especialista foi exercitada apenas com Runner real e modelo roteirizado; o comportamento de roteamento com Gemini real é instável por natureza e deve ser observado via `pytest -m integration`.
- RT-004: o cenário 101 × 302 foi exercitado de ponta a ponta no ADK com modelo roteirizado; permanece pendente a execução com Gemini real; API coberta no Passo 10.

---

## Decisões tomadas e validações restantes

Questões que a validação dos riscos acima deve responder:

- Topologia validada offline; repetir com Gemini; HTTP roteirizado coberto (RT-001/RT-002).
- ID já decidido no Passo 8: `function_call_id` do ADK (ADR-012).
- Ordem implementada: claim PROCESSING → ADK → estado final. Permanece aberta a recuperação automática de falhas ambíguas (RT-001, RT-006).
- Manter regressões da política de transação/espera e resposta a contenção HTTP (RT-003).
- Granularidade e limites da recuperação foram decididos no Passo 9 (artigo; 3 trechos; 3000 caracteres); calibrar com perguntas reais e Gemini (RT-005).
- Restart de pendências já validado entre processos; falta validar com Gemini; HTTP roteirizado coberto (RT-001).

## Revisão de 13/10/2026

- A exportação integral de eventos substitui a projeção resumida em `get_events`; `test_runtime_events.py` cobre partes mistas/metadados e o teste de ouro compara conteúdo completo entre processos. A API usa essa exportação.
- Falha do teto do primeiro trecho corrigida e coberta com parágrafo sintético maior que 3000 caracteres. Nenhum arquivo de `dados/` foi alterado.
- Integração de regulamento reforçada: “não encontrei” não neutraliza indicadores de uma regra inventada. O detector é conservador, não uma prova semântica universal. Gemini continua sem validação quando os testes são pulados por falta de configuração.

## Revisão do Passo 10 (HTTP)

Evidências em `tests/api/` com LLM roteirizado; nenhum risco foi dado como encerrado só por existir endpoint.

- **RT-001:** pendência sobrevive a restart de processo `uvicorn` e é aprovada depois (`test_api_restart.py`). Pendente: Gemini real.
- **RT-003:** duas aprovações HTTP simultâneas (101 × 201, salão, 2030-05-11) → `200`/`200` e exatamente uma reserva ativa; sem `500`. Carga moderada de 10 sessões coberta no Passo 11; Gemini pendente.
- **RT-004:** sessão 101 afirmando ser o 302 não obtém `RSV-4821` nem visitante do 302, nem na resposta nem nos eventos; cancelamento alheio devolve `not_found`. Pendente: injeção de prompt com modelo real.
- **RT-005:** eventos HTTP da consulta à piscina contêm só os trechos recuperados. Pendente: perguntas variadas com Gemini.
- **RT-006:** replay, ID inexistente e ID de outra sessão → `409` sem novo efeito. Pendente: reconciliação de `PROCESSING` órfão.


## Revisão de 16/10/2026 — Passos 10 e 11

A API reconcilia pendências presentes somente nos eventos ADK antes do claim e ao compor a lista
pública. Inserts idempotentes não reabrem confirmações respondidas ou em `PROCESSING`.
A limitação de recuperação de `PROCESSING` órfão permanece e não deve ser confundida com esse caso.

A infraestrutura de testes distingue shutdown cooperativo de crash abrupto e verifica empates
de timestamp por ID. O cenário composto com Gemini agora usa dois processos reais sequenciais;
continua sem execução live enquanto faltarem credenciais/modelo. O limite de 25 chamadas e o
tratamento 502/422 estão registrados em ADR-016; a integração HTTP da recuperação, em ADR-015.
Duas pendências na mesma sessão já têm cobertura adversarial offline, inclusive fora de ordem.

Resultados e limites por execução: [testes-adversariais.md](testes-adversariais.md#revisão-de-16102026--correções-da-auditoria).
As contagens das seções anteriores são históricas, não resultados da revisão atual.


## RT-007 — Custo e disponibilidade em laços do modelo

**Estado:** mitigado por `MAX_LLM_CALLS_PER_RUN = 25`, com regressões F-1 em
`tests/adversarial/test_regressions.py`. O teto limita chamadas por execução, não custo total
por sessão. Em mensagens o erro é 502; durante confirmação segue o tratamento 500/503 da
retomada. **Residual:** calibrar o teto com Gemini antes de declarar os fluxos live validados.

## RT-008 — Serialização de entrada inválida na resposta de erro

**Estado:** mitigado pelo handler 422 que não ecoa input (`app/api/errors.py`).
Regressões F-2 cobrem NaN, Infinity e overflow numérico. Não há tradução de todo erro inesperado
para 4xx: falhas internas continuam detectáveis como 500.

## RT-009 — Evidência instável de restart e ordem dos eventos

**Estado:** infraestrutura revisada em 16/10. A auditoria observou `disk I/O error` após
encerramento abrupto no Windows; a causa completa não foi demonstrada. O restart normal agora
aguarda shutdown do lifespan via pipe; crash continua um teste separado. Não foram introduzidos
retries de leitura para ocultar erros SQLite. Eventos artificiais usam timestamps explícitos,
e empates têm teste específico da ordem por ID. Resultados completos em `testes-adversariais.md`.

## RT-010 — Cota e indisponibilidade do Gemini

**Estado:** ABERTO. `app/agents/model.py` repete 408/429/5xx com backoff exponencial
(`HttpRetryOptions`, 8 tentativas). Se a cota acabar e os retries não bastarem, a mensagem
termina em HTTP 500, sem traceback no corpo. O free tier observado no Passo 12 (5 req/min,
20 req/dia) não comporta um run do fluxo do avaliador. Mapear erros do provedor para 503 não foi
implementado.
