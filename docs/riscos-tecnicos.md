# Riscos técnicos — Residencial Aurora

> **Status do documento (11/10/2026):** registro de riscos com evidências dos Passos 2 a 7 e das regressões de integridade e contenção. A seção de status de cada risco distingue o que foi validado e o que permanece pendente.
> "Como validar" descreve o plano completo; verificações já executadas estão identificadas nas evidências e em [garantias.md](garantias.md#estado-atual-e-evidências). Arquivo existente não implica funcionalidade implementada.

Documentos relacionados: [`garantias.md`](garantias.md) · [`decisoes-arquiteturais.md`](decisoes-arquiteturais.md)

## Convenção

- **Status:** `Aberto` (sem validação suficiente), `Em validação` (evidência parcial), `Mitigado` ou `Aceito`. Uma evidência de persistência, Service ou Tool isolada não encerra o risco ponta a ponta. Os cenários e endpoints descritos são requisitos do fluxo futuro quando não marcados como implementados.
- **Impacto:** Alto / Médio / Baixo.

## Resumo

| ID | Risco | Impacto | Garantia afetada | Quando validar |
|---|---|---|---|---|
| [RT-001](#rt-001--tool-confirmation--sessão-persistente) | Tool Confirmation + sessão persistente | **Alto** | 1, 3 | Primeiro marco da implementação |
| [RT-002](#rt-002--retomada-da-confirmação-no-agente-errado) | Retomada da confirmação no agente errado | **Alto** | 1 | Junto com RT-001 |
| [RT-003](#rt-003--concorrência-de-reservas) | Concorrência de reservas | **Alto** | 5 | Assim que o esquema e a gravação de reservas existirem |
| [RT-004](#rt-004--vazamento-de-identidade-entre-apartamentos) | Vazamento de identidade entre apartamentos | **Alto** | 2 | Contínuo, desde a primeira tool |
| [RT-005](#rt-005--excesso-de-conteúdo-do-regulamento-nos-eventos) | Excesso de conteúdo do regulamento nos eventos | Médio | 4 | Quando a tool de regulamento existir |
| [RT-006](#rt-006--reutilização-de-confirmation-id) | Reutilização de confirmation ID | **Alto** | 1 | Junto com o endpoint de confirmações |

**Ordem de prioridade sugerida:** RT-001 e RT-002 primeiro (bloqueiam a Garantia 1 e influenciam a topologia dos agentes); depois RT-003 e RT-006; RT-004 e RT-005 acompanham a criação de cada tool.

---

## RT-001 — Tool Confirmation + sessão persistente

### Status
**Mitigado / validado na versão atual (Google ADK 2.9.1) com LLM roteirizado — Passo 8.** Ainda **não** exercitado com Gemini real nem via API HTTP. Histórico (Passo 7), dividido em:

| Parte | Situação |
|---|---|
| Tool Confirmation em sessão compatível (`InMemorySessionService`, Runner real, ADK 2.9.1) | **Validado** com LLM roteirizado (`tests/test_tool_confirmation_scripted.py`): pausa, `FunctionResponse` formal, retomada, aprovação grava uma vez, rejeição não grava. Com Gemini real: testes escritos em `tests/integration/test_tool_confirmation.py`, **não executados** onde não havia chave. |
| Tool Confirmation + `DatabaseSessionService` + SQLite + restart | **Validado no Passo 8 (ADK 2.9.1, `ResumabilityConfig(is_resumable=True)`)**: pendência criada no processo A, runtime reconstruído por completo em processo separado, aprovação/rejeição retomam a invocation correta e a Tool original executa (ou é rejeitada) uma única vez; reenvio falha com `ConfirmationNotPendingError`. Testes: `tests/test_confirmation_restart.py` (subprocessos), `tests/test_persistent_confirmation.py`, `tests/test_concurrent_confirmations.py`. Arquivos: `app/runtime/adk_runtime.py`, `app/services/confirmation_service.py`, `app/repositories/confirmation_repository.py`. Só o **modelo** é falso nesses testes. |

**Riscos residuais do RT-001:** (1) Gemini real: `tests/integration/test_persistent_confirmation_gemini.py` existe e é pulado sem `GOOGLE_API_KEY`/`GEMINI_MODEL`; (2) a resumability do ADK é *at-least-once* e `ResumabilityConfig` é experimental — qualquer atualização do ADK exige reexecutar os testes acima; (3) queda do processo **durante** a retomada deixa a confirmação em `PROCESSING` (seguro contra duplicação, porém sem reconciliação automática: requer verificação manual do efeito no domínio); (4) não há transação única entre `adk_sessions.db` e `condominio.db` — a reconciliação cobre apenas o caso "ADK gravou, tabela não".

**Evidência parcial (Passo 2):** `DatabaseSessionService` + SQLite persistiu sessão, `state` e evento mínimo entre processos distintos. **Isto NÃO resolve o RT-001:** Tool Confirmation com sessão persistida e a retomada após aprovação continuam **não validadas** (exigem agente/Runner, previstos para etapa posterior).

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

### Mitigação planejada
- Isolar toda a integração em `AdkRuntime` ([ADR-010](decisoes-arquiteturais.md#adr-010--isolamento-da-integração-adk-em-adkruntime)).
- Manter controle próprio de confirmações ([ADR-012](decisoes-arquiteturais.md#adr-012--controle-próprio-de-confirmações-além-do-estado-do-adk)) com `invocation_id` e `agent_name`.
- **Nunca** reportar sucesso ao morador sem verificar que a ação executou (o resultado vem da tool/serviço, não do texto do modelo).
- Validar com **sessão persistida desde o primeiro teste**, não só em memória.
- Fixar a **versão exata** do ADK e reexecutar a validação em qualquer atualização.

### Como validar
> **Planejado:** construir cedo um protótipo mínimo — Concierge + um especialista com uma tool que exige confirmação, `DatabaseSessionService` em SQLite — e verificar:

1. aprovar → a ação executa **uma vez**;
2. negar → nada executa;
3. aprovar **depois de reiniciar a API** → a ação executa;
4. reenviar a aprovação → `409`, sem nova execução;
5. o resultado da tool é visível nos eventos da sessão.

**Prioridade atual:** validar antes de integrar agentes e API. A recomendação inicial era testar antes das demais tools; as tools isoladas já existem, mas não resolvem esse risco. O resultado pode alterar a topologia dos agentes (ADR-002).

---

## RT-002 — Retomada da confirmação no agente errado

### Status
**Validado na versão atual com LLM roteirizado** — Passo 7 (InMemory) e **Passo 8**: com `DatabaseSessionService`, resumability e restart real, a resposta formal retomou a Tool no agente que a pediu (`reservation_agent` / `visitor_agent`, conferido em `agent_name`, eventos e efeito no banco) e duas confirmações independentes simultâneas (sessões diferentes) foram retomadas sem interferência. Topologia mantida. Pendentes: Gemini real e duas confirmações pendentes na **mesma** sessão.

### Impacto
**Alto.** Afeta diretamente a Garantia 1 e a escolha da topologia de agentes.

### Descrição
Com Concierge e especialistas, a pausa pode acontecer **dentro** de um especialista. A resposta do morador precisa chegar **ao agente que pediu** a confirmação; quem escolhe o agente que recebe a retomada é o Runner, e essa escolha pode variar conforme a topologia, as regras de transferência entre agentes, a configuração de retomada do App e o serviço de sessão.

### Cenário de falha
1. O Reservas Agent pede confirmação.
2. O morador aprova; o Runner entrega a resposta ao Concierge (ou a outro agente).
3. O agente que recebe não possui a chamada pendente: a retomada não ocorre e nada é executado — sem erro visível.

Também: duas confirmações pendentes na mesma sessão (por exemplo, reserva e visitante) sendo retomadas no agente trocado.

### Mitigação planejada
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
**Mitigado no domínio** (Passo 4, 11/10/2026) — `tests/test_reservation_concurrency.py` comprova, sobre Service → Repository → SQLite temporário com sessões independentes, 1 sucesso + 1 `AreaUnavailableError` + 1 reserva ATIVA (101 × 201, salão, 2030-05-11), 25 repetições sem duplicidade, rollback seguido de nova operação, liberação após cancelamento e unicidade de código sob concorrência. **Não encerrado:** falta a validação concorrente via API + confirmações. Contenção prolongada no domínio foi corrigida e coberta por regressões (abaixo).

**Evidência histórica anterior (Passos 2 e 3, 11/10/2026; não descreve toda a suíte atual):** `scripts.check_constraints` passou em banco temporário, incluindo o índice único parcial `uq_reservas_area_data_ativa`. O teste `test_concurrent_creation_single_winner` verifica um sucesso, um `AreaUnavailableError` e uma única reserva ATIVA persistida para 101 × 201 no salão em 2030-05-11. O teste `test_concurrent_many_single_winner`, com seis apartamentos, verifica um sucesso e cinco erros de domínio, mas não conta o estado final. Mensagens sem dados de terceiros são verificadas em testes separados de data ocupada e cancelamento alheio, não nos testes concorrentes.

**Falha histórica (corrigida nesta revisão):** em banco temporário, manter `BEGIN IMMEDIATE` em outra conexão além de `busy_timeout=5000` fazia criar reserva, cancelar reserva e autorizar visitante propagarem `sqlalchemy.exc.OperationalError` (`database is locked`). A regressão agora está em `tests/test_persistence_failures.py`: o domínio devolve `StorageBusyError`, sem efeito parcial, e aceita nova operação após liberar o bloqueio.

**Correção implementada:** `app/services/_persistence.py` traduz apenas `SQLITE_BUSY`/`SQLITE_LOCKED` (incluindo códigos estendidos), após encerrar a sessão; as seis tools devolvem `temporarily_unavailable`, sem SQL. Mantém-se `busy_timeout=5000`, sem retry automático; banco ocupado não significa área ocupada. API/ADK e duas respostas HTTP `200` continuam pendentes de etapas posteriores.

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
**Mitigado em Services e Tools isoladas; aberto ponta a ponta.** Os testes dos Passos 3 e 5 comprovam filtros por apartamento, disponibilidade booleana, cancelamento alheio neutro e ausência de identidade no schema. As tools obtêm o apartamento exclusivamente de `tool_context.state`, sem fallback. Evidências: `tests/test_reservation_tools.py`, `tests/test_visitor_tools.py` e `tests/test_tool_schemas.py`.

**Limite:** os testes usam contexto simulado; duas chamadas também passam por `FunctionTool.run_async`. Não existem criação de sessão pela API, conversa com Agent/Runner nem inspeção de eventos reais. O helper não autentica moradores; a futura camada de criação de sessão deve validar e proteger o estado. Disponibilidade valida presença/formato da identidade, mas não a existência do apartamento no cadastro.

### Impacto
**Alto.** Quebra a Garantia 2; envolve dados de outros moradores.

### Descrição
Mesmo com a identidade vinda da sessão, dados de outros apartamentos podem vazar por **saídas** das tools: mensagens de erro, resultados de consulta, resposta de conflito. Tudo que uma tool devolve entra na conversa **e nos eventos persistidos**, que a futura API deverá expor por completo (`GET /sessoes/{id}/eventos`).

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
Aberto

### Impacto
Médio. Compromete a Garantia 4 (custo e conteúdo dos eventos); não expõe dados de moradores.

### Descrição
O retorno da tool de regulamento fica registrado nos eventos e acompanha o histórico seguinte. Se a seleção do trecho for ampla, assuntos sem relação entram no histórico. A estratégia de seleção ainda é provisória ([ADR-009](decisoes-arquiteturais.md#adr-009--regulamento-consultado-sob-demanda)).

### Cenário de falha
- A tool devolve um capítulo grande (ou o arquivo todo) para uma pergunta pontual.
- O trecho devolvido mistura assuntos de outros capítulos.
- O agente principal ou algum especialista recebe o texto nas instruções por engano.
- Pergunta ambígua faz a seleção devolver trechos demais ou de assuntos errados.

### Mitigação planejada
- Retorno limitado por código (granularidade menor que o arquivo e, se possível, que o capítulo).
- Limite de tamanho no retorno da tool.
- Resposta de "não encontrado" em vez de fallback para o texto completo.
- Instruções dos agentes sem regulamento.

### Como validar
> **Planejado:**

1. Perguntar sobre a piscina aos domingos; conferir o horário correto segundo o regulamento.
2. Inspecionar os eventos: sem trechos de outros assuntos.
3. Variar perguntas (assuntos diferentes, perguntas vagas) e medir o tamanho dos retornos.
4. Conferir as instruções do Concierge e dos especialistas.

**Momento recomendado:** quando a tool de regulamento existir.

---

## RT-006 — Reutilização de confirmation ID

### Status
Aberto — **Passo 7 (descoberta, não proteção):** o ADK não impede a segunda resposta ao mesmo `id`; ele re-executa a Tool. Reserva ficou contida só pela exclusividade do banco; **autorização de visitante duplicou (2 registros)**. `id` inexistente levanta `ValueError` no ADK. A garantia (409 / execução única) precisa ser implementada pela aplicação no Passo 8.

### Impacto
**Alto.** Pode causar execução duplicada de ação com cobrança ou liberação de acesso.

### Descrição
Uma confirmação já respondida (aprovada ou negada) não deve poder ser usada de novo. Reuso pode ocorrer por reenvio do cliente, repetição de requisição, `id` de outra sessão ou duas respostas simultâneas à mesma confirmação.

### Cenário de falha
- O mesmo `id` aprovado duas vezes executa a ação duas vezes.
- Um `id` de outra sessão é aceito.
- Duas requisições simultâneas passam pela checagem de `PENDING` antes de a primeira atualizar o estado.
- Um `id` negado depois é aprovado.

### Mitigação planejada
- Somente `PENDING` **da sessão** aceita resposta; caso contrário, **409**.
- Transição de estado **atômica** (por exemplo, atualização condicionada ao estado `PENDING` e verificação de linhas afetadas), evitando duas vitórias na corrida.
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
- RT-004: o cenário 101 × 302 foi exercitado de ponta a ponta no ADK com modelo roteirizado; permanece pendente a execução com Gemini real e via API.

---

## Pontos que precisarão de decisão durante a implementação

Questões que a validação dos riscos acima deve responder:

- Validação da escolha inicial `sub_agents` + transferência e eventual revisão da topologia (RT-001/RT-002).
- Relação entre o `id` de confirmação do backend e o identificador da chamada pendente no ADK (RT-006, RT-001).
- Ordem entre transição de estado, retomada do ADK e gravação do efeito de negócio, e recuperação de falha entre elas (RT-001, RT-006).
- Validar a política já implementada de transação/espera e resposta a contenção na integração HTTP (RT-003).
- Granularidade, ranqueamento e limites da recuperação inicial por estrutura/palavras-chave (RT-005).
- Mecanismo que preservará o comportamento esperado de confirmações pendentes depois de um reinício: continuar respondíveis e executar uma única vez quando aprovadas (RT-001).
