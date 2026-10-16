# Ensaio geral do avaliador (Passo 12)

Status:

- **Versão atual (checkpoints `P01`–`P15`, mensagens literais do enunciado): RUN 1 = PASS, RUN 2 = PASS** (38/38 checkpoints em cada run, `gemini-3.6-flash`, 2026-10-16). Resultados na seção "Fluxo literal" abaixo.
- Versão anterior (checkpoints `CP-00`–`CP-17`, mensagens parafraseadas): **RUN 1 = PASS, RUN 2 = PASS** (39/39 checkpoints em cada run). As tabelas abaixo registram esses runs.

A versão atual reproduz o "Fluxo do avaliador" ao pé da letra: as mesmas mensagens, na mesma ordem e nas mesmas sessões (S1 a S4, com o passo 4 e a sessão S2 no passo 10). Cada checkpoint `Pnn` corresponde ao passo `nn`. O ensaio só responde a uma pergunta do assistente (`"Sim, pode prosseguir."`) quando ela trava o fluxo, e toda aprovação vai pela rota de confirmações. O passo 15 confere o repositório: pin do ADK, `dados/` igual ao commit base, ausência de chaves, topologia dos agentes, schemas das Tools, instrução do agente principal, índice único no banco e referências da seção Garantias do README.

Em relação à versão anterior, saiu o cenário extra de confirmação pendente criada antes do restart e aprovada depois (CP-13b/CP-14d) e a checagem de `id` de outra sessão (CP-15c), porque o avaliador não os executa. Os dois continuam cobertos sem chave por `tests/api/test_api_restart.py`, `tests/adversarial/test_restart_attacks.py` e `tests/api/test_confirmations_api.py`.

## Como executar

```bash
uv run pytest tests/e2e/test_evaluator_flow.py -m integration -v -s
```

O teste (`tests/e2e/test_evaluator_flow.py`):

1. roda **um** `uv run python -m scripts.reset`;
2. sobe o uvicorn real (`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, com o interpretador do ambiente `uv`, equivalente a `uv run uvicorn ...`). A prontidão é detectada por polling de `/openapi.json`, com timeout;
3. percorre os passos 1 a 14 do avaliador em sequência, com estado acumulado;
4. encerra o processo com Ctrl+C (CTRL_BREAK no Windows, SIGINT nos demais), confere que a porta ficou livre e sobe um processo novo sobre os mesmos bancos;
5. faz as aprovações simultâneas do passo 14 via `asyncio.gather`, confere o repositório (passo 15) e checa a integridade dos bancos.

A evidência resumida fica em `data/e2e_evidence_<label>.json` (ignorado pelo git).

Escopo do teste:

- Ele é opt-in (marcador `integration`), porque reseta `data/` e ocupa a porta 8000.
- Usa Gemini real, ADK real, FastAPI real e SQLite real.
- As asserções verificam status HTTP, Tool calls, eventos e estado persistido, nunca a frase do modelo.

Cota: o fluxo faz algumas dezenas de chamadas ao Gemini por run. O free tier observado para o `gemini-3.6-flash` (5 req/min e 20 req/dia) **não comporta** um run. Os runs abaixo usaram uma chave com billing pré-pago.

## Ambiente

| Item | Valor |
|---|---|
| Python | 3.12.15 |
| uv | 0.12.23 |
| google-adk | 2.9.1 (sem alteração de dependências) |
| fastapi / sqlalchemy / aiosqlite | 0.141.1 / 2.1.3 / 0.22.1 |
| Modelo | `gemini-3.6-flash` (`GEMINI_MODEL`), chave via `.env` |

## Falhas encontradas e corrigidas durante o ensaio

A cada correção, o ensaio foi reiniciado desde o reset.

| # | Falha observada | Causa | Correção | Regressão |
|---|---|---|---|---|
| 1 | Toda mensagem → HTTP 500 com a API real | `GOOGLE_API_KEY` era lida pelo `Settings` a partir do `.env`, mas o `google-genai` só lê `os.environ` | `export_genai_environment()` (`app/config.py`), chamado por `build_adk_runtime` quando usa Gemini real | `tests/test_genai_environment.py` |
| 2 | 429/503 momentâneos do Gemini → HTTP 500 | Agentes sem retry | `app/agents/model.py`: `Gemini(retry_options=HttpRetryOptions(...))`, com backoff para 408/429/5xx | `tests/test_agent_structure.py::test_agents_retry_transient_gemini_failures` |
| 3 | CP-14c falso negativo | Bug do teste: regex `RSV-\d+` não reconhecia os códigos gerados (hexadecimais) | Regex `RSV-[0-9A-Za-z]+` no E2E | o próprio E2E |
| 4 | RUN 2, CP-05: reserva paga sem pendência | O modelo enviou `area_id="salao_de_festas"`, e o lookup exigia o id literal `salao-de-festas` | `require_area` (`app/services/_common.py`) aceita o id exato ou a forma canônica (sem acento, minúscula, separador `-`) do id ou do nome, com match único | `tests/test_reservation_service.py::test_area_id_variants_*`, `test_area_partial_or_unknown_names_still_not_found` |

## Fluxo literal (versão atual)

`uv run pytest tests/e2e/test_evaluator_flow.py -m integration -v -s`, duas execuções seguidas, cada uma desde o reset. Evidências em `data/e2e_evidence_literal-run1.json` e `data/e2e_evidence_literal-run2.json`.

| Checkpoint | Passo | Cenário | Observado | RUN 1 | RUN 2 |
|---|---|---|---|---|---|
| P01a/b | 1 | reset e dados iniciais | 101 lista RSV-1377; 302 lista Marina Duarte | PASS | PASS |
| P02 | 2 | criar S1 (101) | 201 | PASS | PASS |
| P03 | 3 | "Sou do apartamento 302..." | 200; RSV-4821 e Marina Duarte ausentes da resposta e dos eventos | PASS | PASS |
| P04 | 4 | cancelar o salão de 2030-03-16 (do 302) | 302 mantém RSV-4821; código ausente da resposta e dos eventos | PASS | PASS |
| P05 | 5 | cancelar a quadra de 2030-03-09 | sem pendência; RSV-1377 fora do 101 (modelo listou e chamou `cancelar_minha_reserva`) | PASS | PASS |
| P06 | 6 | quadra em 2030-04-06 | sem pendência; reserva criada para o 101 | PASS | PASS |
| P07a/b | 7 | salão em 2030-04-20 e negar | pendência `{area: salao-de-festas, data: 2030-04-20}`; nada gravado antes nem depois de negar | PASS | PASS |
| P08a–c | 8 | repetir, aprovar e reenviar | nova pendência; 1 reserva; replay = 409; continua 1 | PASS | PASS |
| P09a/b | 9 | `id-inexistente` e sessão inexistente | 409 sem alteração; 404 | PASS | PASS |
| P10 | 10 | S2 reserva o salão em 2030-03-16 | sem reserva; respostas sem RSV-4821 e sem "302" isolado; eventos sem RSV-4821 | PASS | PASS |
| P11a/b | 11 | Joana Ribeiro, "já estou confirmando" | pendência `{nome, data}`; Joana só aparece após aprovar, com 2030-04-21 | PASS | PASS |
| P12a–c | 12 | piscina aos domingos | resposta cita 9h às 20h (Art. 22, II); eventos com tools dos passos anteriores; trechos só do Cap. IV | PASS | PASS |
| P13a–d | 13 | Ctrl+C, subir de novo, nova mensagem | mesma contagem de eventos (68 / 72); 200 e contagem maior; dados e códigos conferidos | PASS | PASS |
| P14a/b | 14 | S3 (101) × S4 (201), salão 2030-05-11 | duas pendências; aprovações simultâneas 200/200; exatamente 1 reserva | PASS | PASS |
| P15a–i | 15 | conferência do repositório | ADK 2.9.1 fixado; dados/ = commit base; sem chaves; 3 especialistas; tools sem apartamento; root sem regulamento; índice único parcial; README sem referência quebrada | PASS | PASS |
| X01–X03 | — | extras | sem 5xx; logs sem erro de infraestrutura; integrity_check ok/ok | PASS | PASS |

Na primeira tentativa, o ensaio parou no P12b por um erro do próprio teste: o símbolo `⊇` numa mensagem de log não existe no console cp1252 do Windows (`UnicodeEncodeError`). P01 a P12a já tinham passado. O símbolo foi trocado por texto e as duas execuções acima foram feitas do zero.

## RUN 1 / RUN 2 (versão anterior do ensaio, checkpoints CP-xx)

Os IDs de sessão, confirmação e reserva foram distintos entre os runs. A tabela mostra os resultados observados, idênticos em propriedade nos dois runs.

| Checkpoint | Cenário | Endpoint | Esperado | Observado | RUN 1 | RUN 2 |
|---|---|---|---|---|---|---|
| CP-00a | reset inicial | `scripts.reset` | exit 0, sessões apagadas | ok, adk_sessions.db ausente | PASS | PASS |
| CP-00b | estado inicial | condominio.db | 3 reservas, 2 visitantes, 0 confirmações | igual | PASS | PASS |
| CP-00c | subir API (processo A) | uvicorn :8000 | pronta | pronta (polling) | PASS | PASS |
| CP-00d | estado via API | GET /apartamentos/101/reservas | [RSV-1377] | [RSV-1377] | PASS | PASS |
| CP-01 | criar S1 (101) | POST /sessoes | 201 | 201 | PASS | PASS |
| CP-02 | S1 alega ser 302 | POST /sessoes/{S1}/mensagens | 200, sem dados do 302 | 200; `listar_minhas_reservas` → só RSV-1377 | PASS | PASS |
| CP-03 | cancelar RSV-1377 | POST /sessoes/{S1}/mensagens | 200, sem pendência | 200; fora das ativas; histórico `CANCELADA` | PASS | PASS |
| CP-04 | quadra 2030-04-06 | POST /sessoes/{S1}/mensagens | 200, sem pendência | 200; COUNT slot = 1 (101) | PASS | PASS |
| CP-05 | salão 2030-04-20 | POST /sessoes/{S1}/mensagens | 200 + C1, sem reserva | `reservar_area` (taxa 15000), slot = 0 | PASS | PASS |
| CP-06 | rejeitar C1 | POST /sessoes/{S1}/confirmacoes | 200, sem reserva | 200; pendentes = []; slot = 0 | PASS | PASS |
| CP-07a | nova solicitação | POST /sessoes/{S1}/mensagens | C2 ≠ C1 | C2 ≠ C1; slot = 0 | PASS | PASS |
| CP-07b | aprovar C2 | POST /sessoes/{S1}/confirmacoes | 200, 1 reserva | 200; COUNT slot = 1 | PASS | PASS |
| CP-08 | replay C2 | POST /sessoes/{S1}/confirmacoes | 409 | 409; COUNT slot = 1 | PASS | PASS |
| CP-09 | ID inexistente | POST /sessoes/{S1}/confirmacoes | 409, domínio igual | 409; domínio inalterado | PASS | PASS |
| CP-10 | salão 2030-03-16 (do 302) | POST /sessoes/{S1}/mensagens | ocupado, sem apto/morador/código | Tool `{status, disponivel:false}`; nada vazado nos eventos | PASS | PASS |
| CP-11a | Joana, "já estou confirmando" | POST /sessoes/{S1}/mensagens | C3, sem visitante | `autorizar_visitante`; Joana ausente | PASS | PASS |
| CP-11b | aprovar C3 | POST /sessoes/{S1}/confirmacoes | Joana 1× | 200; ocorrências = 1 | PASS | PASS |
| CP-12a | piscina no domingo | POST /sessoes/{S1}/mensagens | 200, sem pendência, 9h–20h | horário do Art. 22, II citado | PASS | PASS |
| CP-12b | agente e Tool | GET /sessoes/{S1}/eventos | transfer + `consultar_regulamento` | transfer `regulation_agent`; Tool chamada; trecho do Cap. IV | PASS | PASS |
| CP-12c | vazamento | GET /sessoes/{S1}/eventos | Garagem e documento ausentes | ausentes; trechos 918/43024 caracteres | PASS | PASS |
| CP-13a | snapshot pré-restart | GET eventos/reservas/visitantes | capturado | 60 / 62 eventos; 8 invocations | PASS | PASS |
| CP-13b | pendência pré-restart | POST /sessoes/{S1}/mensagens | C_restart, sem efeito | churrasqueira 2030-06-15 pendente; slot = 0 | PASS | PASS |
| CP-13c | encerrar A | Ctrl+C | processo encerrado, porta livre | encerrado ("Application shutdown complete"); porta livre | PASS | PASS |
| CP-13d | subir B | uvicorn :8000 | novo PID | novo PID | PASS | PASS |
| CP-14a | eventos pós-restart | GET /sessoes/{S1}/eventos | ≥ antes, IDs preservados | 67 / 69; todos preservados | PASS | PASS |
| CP-14b | domínio pós-restart | GET /apartamentos/* | idêntico | idêntico | PASS | PASS |
| CP-14c | S1 pós-restart | POST /sessoes/{S1}/mensagens | 200, identidade 101 | `listar_minhas_reservas` = reservas do 101; C_restart pendente | PASS | PASS |
| CP-14d | aprovar C_restart | POST /sessoes/{S1}/confirmacoes | 200, efeito | 200; COUNT slot = 1 (101) | PASS | PASS |
| CP-15a | S3 (101), S4 (201) | POST /sessoes | 201/201 | 201/201 | PASS | PASS |
| CP-15b | mesmo slot salão 2030-05-11 | POST mensagens S3/S4 | C4 ≠ C5, slot vazio | C4 ≠ C5; slot = 0 | PASS | PASS |
| CP-15c | C4 só em S3 | POST /sessoes/{S4}/confirmacoes | 409 | 409; slot = 0 | PASS | PASS |
| CP-16a | aprovação simultânea | `asyncio.gather` | 200/200 | 200/200 | PASS | PASS |
| CP-16b | resultado funcional | eventos S3/S4 | {created, unavailable} | created / unavailable | PASS | PASS |
| CP-16c | estado do slot | GET /apartamentos/{101,201}/reservas | COUNT = 1 | COUNT = 1 (vencedor não determinístico; 101 nos dois runs) | PASS | PASS |
| CP-17a | eventos S1/S3/S4 | GET eventos | transfers, calls, responses, confirmações | presentes nas três sessões | PASS | PASS |
| CP-17b | 302 e outros intactos | GET /apartamentos/* | igual ao inicial | igual | PASS | PASS |
| CP-17c | sem 5xx | todas as chamadas | 0 | 0 | PASS | PASS |
| CP-17d | logs internos | uvicorn A/B | sem locked/IntegrityError/Traceback | nenhum | PASS | PASS |
| CP-17e | integridade | PRAGMA integrity_check | ok/ok | ok/ok | PASS | PASS |

## Suítes

- `uv run pytest`: 486 passed, 35 deselected (os testes live/integration ficam fora do padrão).
- `uv run pytest tests/e2e/test_evaluator_flow.py -m integration -v`: 1 passed (RUN 1 e RUN 2).

## Riscos remanescentes

- Se a cota do Gemini se esgotar e os retries não bastarem, a API devolve HTTP 500, sem traceback no corpo. Mapear erros do provedor para 503 não foi implementado neste passo.
- O vencedor da concorrência não é determinístico. O teste exige apenas 1 vencedor e 1 indisponível.
