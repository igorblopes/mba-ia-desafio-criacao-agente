# Decisões arquiteturais — Residencial Aurora

> **Estado final (Passo 13, 16/10/2026):** implementação concluída e congelada. As cinco garantias estão implementadas e cobertas por testes offline (`uv run pytest`: 486 passed, 35 deselected) e pelo ensaio integral do avaliador com **Gemini real, uvicorn real e restart real** (RUN 1 = PASS, RUN 2 = PASS; [ensaio-avaliador.md](ensaio-avaliador.md)). O [README](../README.md) é a descrição autoritativa do sistema final; as seções datadas deste documento são registro histórico, e menções a "Gemini pendente" nelas descrevem o estado anterior ao Passo 12.
> **Aceita** indica decisão, não comprovação de funcionamento. Resultados e limites dos testes constam em [garantias.md](garantias.md#estado-atual-e-evidências).
> Nomes de arquivos citados nas ADRs são os da implementação final (inventário em [`arquitetura.md`](arquitetura.md#12-estrutura-do-repositório)).

**Princípio que guia todas as decisões:**

> O modelo conduz a conversa e decide o caminho da interação, mas o código e o banco de dados decidem o que é permitido. O LLM nunca é uma barreira de segurança.

## Convenção de status

- **Aceita** — decisão tomada; mudanças futuras devem ser comparadas a ela e registradas como nova ADR ou revisão.
- **Provisória** — decisão ainda não fechada. Quando uma ADR "Aceita" tem um ponto específico em aberto, esse ponto aparece em uma subseção **Pontos provisórios** e na lista final.

## Índice

| ADR | Título | Status |
|---|---|---|
| [ADR-001](#adr-001--fastapi-como-camada-http) | FastAPI como camada HTTP | Aceita |
| [ADR-002](#adr-002--arquitetura-multiagente) | Arquitetura multiagente | Aceita (validada offline e com Gemini real no ensaio E2E) |
| [ADR-003](#adr-003--três-especialistas-além-do-agente-principal) | Três especialistas além do agente principal | Aceita |
| [ADR-004](#adr-004--agent--tool--service--repository) | Agent → Tool → Service → Repository | Aceita |
| [ADR-005](#adr-005--sqlite-como-armazenamento) | SQLite como armazenamento | Aceita |
| [ADR-006](#adr-006--bancos-separados-para-domínio-e-sessões-do-adk) | Bancos separados para domínio e sessões do ADK | Aceita |
| [ADR-007](#adr-007--identidade-obtida-exclusivamente-da-sessão) | Identidade obtida exclusivamente da sessão | Aceita |
| [ADR-008](#adr-008--integridade-concorrente-garantida-pelo-banco) | Integridade concorrente garantida pelo banco | Aceita (índice implementado; contenção traduzida no domínio) |
| [ADR-009](#adr-009--regulamento-consultado-sob-demanda) | Regulamento consultado sob demanda | Aceita (implementada no Passo 9; busca lexical local) |
| [ADR-010](#adr-010--isolamento-da-integração-adk-em-adkruntime) | Isolamento da integração ADK em `AdkRuntime` | Aceita |
| [ADR-011](#adr-011--histórico-de-reservas-canceladas-mantido) | Histórico de reservas canceladas mantido | Aceita |
| [ADR-012](#adr-012--controle-próprio-de-confirmações-além-do-estado-do-adk) | Controle próprio de confirmações além do estado do ADK | Aceita (implementada; recuperação parcial) |
| [ADR-013](#adr-013--camada-de-service-erros-de-domínio-e-separação-request--execução-confirmada) | Services e execução confirmada separada | Aceita (contenção tratada; outros erros operacionais propagam) |
| [ADR-014](#adr-014--reset-apaga-sessões-por-padrão-passo-8) | Reset apaga sessões por padrão | Aceita (revisa parte da ADR-006) |
| [ADR-015](#adr-015--recuperação-de-pendências-também-no-contrato-http-16102026) | Reconciliação no fluxo HTTP | Aceita |
| [ADR-016](#adr-016--limites-de-execução-e-erros-http-seguros-passo-11) | Limites e erros HTTP seguros | Aceita |
| [ADR-017](#adr-017--reinício-normal-distinto-de-crash-nos-testes-16102026) | Shutdown, crash e ordem dos eventos | Aceita |

---

## ADR-001 — FastAPI como camada HTTP

### Status
Aceita

### Contexto
O assistente precisa ser exposto por uma API HTTP com rotas de conversa, confirmação, eventos e verificação. O projeto usa Python e o Google ADK, que é assíncrono.

### Decisão
Usar **FastAPI** como camada HTTP.

### Motivos
- Suporte nativo a `async`, compatível com o padrão do runtime do ADK.
- Validação de entrada e códigos de status explícitos (`201`, `404`, `409`).
- Roteamento simples para separar rotas de conversa e rotas de verificação.

### Consequências
- A camada HTTP deve permanecer **fina**: valida entrada, chama `AdkRuntime` ou serviços e devolve JSON.
- Regras de negócio **não** ficam nas rotas.

### Alternativas consideradas
- **Flask / outro framework web:** viável, mas com menos afinidade com o fluxo assíncrono do ADK.
- **Usar apenas as ferramentas de desenvolvimento do ADK:** não oferece o contrato HTTP exigido.

---

## ADR-002 — Arquitetura multiagente

### Status
Aceita (sub_agents + transferência implementados e validados offline)

### Contexto
O assistente cobre três domínios com riscos diferentes (reservas, visitantes, regulamento). Concentrar tudo em um único agente aumentaria o contexto, misturaria instruções e dificultaria isolar o que cada domínio pode fazer.

### Decisão
Adotar um **agente principal (Concierge)** com especialistas registrados como **`sub_agents`**, acionados inicialmente por **transferência entre agentes**. O fluxo escolhido para a primeira implementação é: Concierge → transferência → especialista → tools.

### Motivos
- Separação de responsabilidades e de instruções.
- Cada especialista expõe apenas as tools do seu domínio.
- O agente principal não carrega o regulamento nem acessa dados.
- Reduz o tamanho do contexto de cada agente.

### Consequências
- Surge uma dependência importante: a **retomada de uma confirmação** no ADK pode depender de qual agente a solicitou e da topologia dos agentes (ver [RT-001](riscos-tecnicos.md#rt-001--tool-confirmation--sessão-persistente) e [RT-002](riscos-tecnicos.md#rt-002--retomada-da-confirmação-no-agente-errado)).
- A topologia escolhida precisa ser validada **cedo**, com sessão persistida.

### Implementação (Passo 6)
- `concierge_agent` é o root com `sub_agents=[reservation_agent, visitor_agent]`, sem tools de negócio; cada especialista recebe somente as tools do seu domínio (menor privilégio). O Concierge atua só como orquestrador.
- O modelo vem de `get_settings().gemini_model` (configuração central); não há nome de modelo nos agentes, e todos usam o mesmo modelo por ora.
- Regulamento: fora do prompt do Concierge; o Regulation Agent foi conectado no Passo 9 (`sub_agents` do Concierge, única Tool `consultar_regulamento`).
- Evidência: `tests/test_agent_structure.py` e `tests/test_agent_runtime_scripted.py`; a transferência com Gemini real e com Tool Confirmation continua não comprovada.

### Pontos provisórios
- Compatibilidade com Tool Confirmation, sessão persistida e restart comprovada offline no Passo 8 (RT-001/RT-002) e com Gemini real no Passo 12.
- Se a retomada não voltar ao agente que solicitou a confirmação, a topologia poderá mudar; essa revisão deverá ser registrada na ADR, preservando a decisão inicial e a evidência do teste.

### Alternativas consideradas
- **Agente único com todas as tools:** mais simples, mas mistura domínios e aumenta superfície de erro.
- **Roteamento por código fora do ADK:** perde a naturalidade da conversa e o uso dos recursos do framework.

---

## ADR-003 — Três especialistas além do agente principal

### Status
Aceita

### Contexto
É preciso definir quantos especialistas existem e como dividir as responsabilidades.

### Decisão
Criar **três especialistas** além do Concierge:

- **Reservas** — consultar, verificar disponibilidade, solicitar criação, cancelar reservas próprias;
- **Visitantes** — consultar visitantes do próprio apartamento, solicitar autorização;
- **Regulamento** — responder dúvidas consultando trechos do regulamento.

### Motivos
- Cada especialista corresponde a um domínio com regras e riscos próprios:
  - Reservas → cobrança e concorrência;
  - Visitantes → liberação de acesso;
  - Regulamento → tamanho de contexto.
- Tools de um domínio não ficam visíveis aos demais.

### Consequências
- Mais agentes implicam mais chamadas ao modelo por pedido e mais pontos que podem solicitar confirmação.
- Dois dos três especialistas (Reservas e Visitantes) podem pedir confirmação, o que reforça a necessidade de validar a retomada por agente (RT-002).

### Alternativas consideradas
- **Dois especialistas** (juntando Reservas e Visitantes): menos agentes, mas mistura cobrança e acesso.
- **Quatro ou mais especialistas** (por exemplo, separar consulta de escrita): granularidade maior sem benefício claro neste momento.

---

## ADR-004 — Agent → Tool → Service → Repository

### Status
Aceita

### Contexto
É preciso uma separação que impeça o modelo de alcançar dados ou regras sem passar por validação de código.

### Decisão
Adotar as camadas **Agent → Tool → Service → Repository → Database** com responsabilidades fixas (ver [`arquitetura.md`](arquitetura.md#5-camadas)):

- **Agent:** linguagem natural, intenção, orquestração, escolha da tool.
- **Tool:** fronteira LLM ↔ aplicação; expõe operações permitidas; obtém identidade do contexto seguro; limita o retorno.
- **Service:** regras de negócio (reservas, cancelamento, visitantes, validações, geração de códigos).
- **Repository:** exclusivamente persistência e consultas.
- **Database:** integridade que não pode depender só de Python.

### Motivos
- Cada regra crítica tem um lugar único e testável fora do modelo.
- A tool é o ponto onde se impede que o modelo forneça identidade.
- Os services não conhecem ADK nem HTTP, facilitando testes e reuso (as rotas de verificação reutilizam repositórios/serviços sem passar pelo modelo).

### Consequências
- Mais arquivos e indireção.
- Disciplina necessária: nenhuma regra crítica deve "escorregar" para o prompt ou para a tool.

### Implementação (Passo 5)
- Registro explícito de seis `FunctionTool` em `app/tools/__init__.py`, com implementações em `app/tools/reservations.py` e `app/tools/visitors.py`. Os arquivos em português da proposta inicial são placeholders.
- **Tools são adaptadores finos:** convertem data (`AAAA-MM-DD`), chamam o Service e traduzem o resultado para `dict`; não contêm regra de taxa, autorização, SQL nem concorrência. Obtêm Services por `app/services/provider.py`, sem importar SQLAlchemy ou Repositories.
- **Identidade vem exclusivamente de `ToolContext.state["apartamento"]`** (`app/tools/context.py`), sem fallback; ausência → `invalid_session`.
- Tools públicas: `listar_minhas_reservas`, `verificar_disponibilidade`, `solicitar_reserva`, `cancelar_minha_reserva`, `listar_meus_visitantes`, `solicitar_autorizacao_visitante`. `create_confirmed_*` permanecem internos aos Services.
- Histórico: no Passo 5 os testes usavam contexto simulado. Agents, Tool Confirmation e persistência de pendências foram adicionados nos Passos 6–8. A API está implementada desde o Passo 10; a tool de regulamento elevou o total para sete no Passo 9.

### Alternativas consideradas
- **Tools acessando o banco diretamente:** menos código, mas mistura regra, persistência e fronteira com o LLM.
- **Regras nos prompts dos agentes:** rejeitada — violaria o princípio central.

---

## ADR-005 — SQLite como armazenamento

### Status
Aceita

### Contexto
O projeto precisa de persistência de dados de negócio e de sessões, com restrições de integridade (unicidade) e sobrevivência a reinício, sem infraestrutura externa.

### Decisão
Usar **SQLite** como armazenamento.

### Motivos
- Zero dependência de serviço externo (sem container obrigatório).
- Suporta **constraints** e **transações**, essenciais para a Garantia 5.
- Um arquivo por banco simplifica restauração e inspeção.

### Consequências
- SQLite permite **um escritor por vez**; sob concorrência é preciso definir política de transação e de espera (ver [RT-003](riscos-tecnicos.md#rt-003--concorrência-de-reservas)).
- Escala limitada, aceitável para o escopo.

### Alternativas consideradas
- **PostgreSQL ou outro banco em container:** mais robusto para produção, mas exige serviço externo adicional.
- **Armazenamento em memória / arquivos JSON:** não oferece constraints transacionais nem sobrevive bem a concorrência.

---

## ADR-006 — Bancos separados para domínio e sessões do ADK

### Status
Aceita *(adotada "inicialmente"; pode ser revista se surgir necessidade)*

### Contexto
O ADK persiste sessões e eventos em seu próprio esquema. Os dados de negócio têm esquema e ciclo de vida próprios.

### Decisão
Usar dois arquivos SQLite:

```text
data/
├── condominio.db      # dados de negócio
└── adk_sessions.db    # sessões e eventos do ADK
```

### Motivos
- Não misturar o esquema gerenciado pelo ADK com o esquema de negócio.
- Permite restaurar o estado do condomínio sem destruir (ou destruindo, se assim for decidido) sessões.
- Evita acoplamento do domínio à estrutura interna do ADK, que pode mudar entre versões.

### Consequências
- **Não há transação única** entre os dois bancos. Consistência entre eles (por exemplo, confirmação registrada no banco de negócio e sessão no banco do ADK) precisa ser tratada explicitamente na camada `AdkRuntime`.
- O comando de restauração precisa definir o que acontece com as sessões do ADK.

### Pontos provisórios
- ~~Se `scripts/reset.py` também apaga `adk_sessions.db`~~ — **decidido no Passo 2, revisto no Passo 8 ([ADR-014](#adr-014--reset-apaga-sessões-por-padrão-passo-8)):** o reset passou a apagar `adk_sessions.db` por padrão; `--keep-sessions` preserva.

### Evidência (Passo 2)
- `DatabaseSessionService` sobre `sqlite+aiosqlite` em `adk_sessions.db` persistiu sessão, `state["apartamento"]` e um evento mínimo entre dois processos distintos (`uv run python -m scripts.check_session_persistence`).

### Alternativas consideradas
- **Um único banco para tudo:** simplifica transações, mas acopla o domínio ao esquema do ADK.
- **Sessões em memória:** viola a Garantia 3.

---

## ADR-007 — Identidade obtida exclusivamente da sessão

### Status
Aceita

### Contexto
O morador pode escrever qualquer coisa ("Sou do 302", "cancela a reserva dele"). Se o apartamento for um parâmetro de tool preenchido pelo modelo, a identidade fica à mercê de prompt injection.

### Decisão
O apartamento é definido **na criação da sessão** e guardado no estado da sessão (conceitualmente `session.state["apartamento"]`). Tools leem o apartamento do contexto de execução (conceitualmente `tool_context.state["apartamento"]`). **Nenhuma tool** aceita apartamento escolhido livremente pelo modelo.

### Motivos
- Elimina a classe de ataque "o modelo foi convencido a usar outro apartamento".
- A identidade não passa pelo texto da conversa.

### Consequências
- Todas as tools dependem do estado da sessão estar corretamente preenchido; uma sessão sem apartamento deve resultar em recusa, não em fallback para algum valor.
- Retornos de tools devem ser minimizados para **não vazar** dados de terceiros (que iriam também para os eventos).
- Operação sobre reserva inexistente ou de outro apartamento deve devolver resposta indistinguível.

### Implementação e limites (Passo 5)
- `app/tools/context.py` lê apenas `state["apartamento"]`, sem fallback; ausência ou valor sem formato básico retorna `invalid_session` nas tools.
- A assinatura Python recebe `ToolContext`; os schemas gerados pelo ADK omitem esse argumento. `tests/test_tool_schemas.py` verifica os parâmetros visíveis das seis tools.
- Services de operações pessoais validam a existência do apartamento. A consulta de disponibilidade apenas exige identidade no estado e retorna booleano; não autentica nem consulta o cadastro do apartamento.
- A origem confiável do estado continua sendo uma precondição: a API valida o apartamento antes de criar a sessão e não expõe alteração da identidade. O runtime já cria o estado e os testes roteirizados verificam isolamento; Gemini real permanece pendente.

### Alternativas consideradas
- **Apartamento como argumento da tool, validado contra o da sessão:** funciona, mas mantém a superfície de erro e convida a esquecer a validação em uma tool nova.
- **Identidade nas instruções do agente:** rejeitada — dependeria do prompt.

---

## ADR-008 — Integridade concorrente garantida pelo banco

### Status
Aceita *(índice implementado e provado sob concorrência no domínio — Passo 4; contenção traduzida em StorageBusyError)*

### Contexto
Regra crítica: no máximo **uma reserva ativa por área e data**. Dois moradores podem pedir a mesma coisa ao mesmo tempo; uma checagem de disponibilidade seguida de gravação não é segura.

### Decisão
Garantir a exclusividade **no instante da gravação** com:

- **constraint de banco** — conceitualmente `UNIQUE(area, data)` restrita a reservas ativas, ou implementação SQLite equivalente;
- **transação**;
- **tratamento de conflito como resultado normal** (resposta de negócio, não erro de servidor).

### Motivos
- Só o banco enxerga todas as gravações de forma atômica.
- Não depende do que o modelo consultou antes.

### Consequências
- A consulta de disponibilidade passa a ser **conveniência**, não garantia.
- O repositório deve expor o conflito de forma tratável e o service traduzi-lo em resposta sem vazar dados do outro apartamento.
- Como o histórico mantém reservas canceladas ([ADR-011](#adr-011--histórico-de-reservas-canceladas-mantido)), a unicidade precisa valer **somente para reservas ativas**.

### Decisões de implementação e limites
- ~~Forma exata~~ — **decidido no Passo 2:** índice único parcial `uq_reservas_area_data_ativa ON reservas(area, data) WHERE status = 'ATIVA'`, validado por `uv run python -m scripts.check_constraints` (ATIVA+ATIVA bloqueada; CANCELADA+ATIVA permitida).
- **Refinado no Passo 4:** o banco é a última linha de defesa e a consulta de disponibilidade é só UX; cada tentativa de gravação usa **sessão e transação próprias** (nunca uma `AsyncSession` compartilhada entre tarefas); na inserção de reserva, `IntegrityError` é traduzido pelo Service — o repository faz `rollback` e o Service distingue conflito de área/data (`AreaUnavailableError`) de colisão de código (novo código, até 5 tentativas), pela exceção SQLite original (código estendido e colunas), sem consulta posterior; outras violações viram DomainError, não indisponibilidade; WAL, `busy_timeout=5000` e `foreign_keys=ON` são validados no banco de teste. Prova: `tests/test_reservation_concurrency.py`.
- **Classificação SQLite:** `app/services/_persistence.py` combina o código estendido com as colunas informadas na mensagem original. Formatos desconhecidos não são tratados como colisão conhecida; na inserção de reserva resultam em `DomainError`. Uma mudança de driver/formato exige revalidar as regressões.
- **Política de contenção definida nesta revisão:** manter transações atuais, esperar até o timeout e traduzir `SQLITE_BUSY`/`SQLITE_LOCKED` para `StorageBusyError`, sem retry automático. Outros erros operacionais propagam. O Passo 2 configura `busy_timeout=5000` e WAL, que apenas amenizam contenção temporária; a garantia de unicidade vem do índice, não do timeout.

### Alternativas consideradas
- **Verificar disponibilidade e depois gravar:** rejeitada — *check-then-act* sujeito a condição de corrida.
- **Lock em memória no processo Python:** não vale entre processos nem sobrevive a reinício; pode complementar, nunca substituir a constraint.
- **Confiar no modelo para não pedir duas vezes:** rejeitada — violaria o princípio central.

---

## ADR-009 — Regulamento consultado sob demanda

### Status
Aceita *(implementada no Passo 9: consulta local determinística, sem RAG vetorial; qualidade da busca limitada ao léxico do documento)*

### Contexto
O regulamento é longo. Colocá-lo nas instruções ou no histórico aumenta o custo de todas as chamadas e polui os eventos da sessão com assuntos irrelevantes. O conteúdo devolvido por tools é gravado nos eventos.

### Decisão
O regulamento completo **não** entra no prompt do agente principal, nas instruções dos agentes, no `session.state` nem no histórico. A consulta é **local e determinística**, não um RAG vetorial: `RegulationRepository` lê e parseia `dados/regulamento.md` (um trecho por artigo, estrutura Markdown real) e `RegulationService` normaliza a pergunta, ranqueia por IDF com peso extra para o capítulo e devolve no máximo `MAX_RESULTS` trechos / `MAX_RETURNED_CHARS` caracteres, com os textos originais. Perguntas amplas retornam `query_too_broad`; sem evidência suficiente, `not_found`. A Tool `consultar_regulamento(pergunta)` expõe apenas a pergunta; os limites são constantes de código.

### Motivos
- **Arquivo pequeno** (~45 mil caracteres, 96 artigos): não justifica infraestrutura vetorial.
- **Estrutura Markdown** (capítulos e artigos) já oferece unidades de recuperação naturais e citáveis.
- **Offline:** funciona sem `GOOGLE_API_KEY` e sem rede; embeddings remotos adicionariam dependência, custo e latência.
- **Determinismo:** mesma pergunta, mesmo resultado; sem variação entre execuções.
- **Testabilidade:** parser, ranking, limites e vazamento são testados sem Gemini, com expectativas derivadas do arquivo real.
- **Baixo acoplamento:** nenhuma tabela, índice externo ou serviço novo; o Repository mantém só cache em memória.
- Reduz tokens e impede que assuntos não relacionados fiquem nos eventos; a limitação é feita por código, não por pedir ao modelo para "ignorar" conteúdo.

### Consequências
- A qualidade da resposta depende da busca lexical. Sinônimos distantes do texto podem gerar `not_found` (falso negativo seguro). Há poucos sinônimos fixos (barulho→ruído/silêncio, cachorro/gato/pet→animais, hora/funcionamento→horário).
- Pergunta com duas partes: `termos_nao_localizados` permite ao agente responder só o que existe; se a maior parte dos termos não existir, a resposta é `not_found`.
- Os retornos têm tamanho limitado e são inspecionados nos testes de eventos. Revisão de 13/10/2026: o teto de 3000 caracteres de conteúdo somado inclui o primeiro trecho. Unidade indivisível maior é descartada sem truncamento; nenhum trecho elegível resulta em `not_found`. Isso preserva o limite mesmo com documentos futuros maiores.
- Se o documento crescer muito ou o vocabulário dos moradores divergir do texto, revisar a decisão (embeddings locais, por exemplo).

### Alternativas consideradas
- **Regulamento completo no prompt do agente principal:** rejeitada — custo e poluição de contexto.
- **Regulamento completo no prompt do especialista:** rejeitada — as instruções acompanham todas as chamadas daquele agente.
- **Retornar o arquivo inteiro pela tool:** rejeitada — iria para os eventos da sessão.
- **RAG vetorial (FAISS/Chroma/embeddings):** rejeitada nesta etapa — complexidade e dependência externas sem necessidade para um arquivo pequeno e estruturado.
- **Pedir ao Gemini que escolha a parte relevante a partir do documento inteiro:** rejeitada — enviaria o documento ao modelo.

---

## ADR-010 — Isolamento da integração ADK em `AdkRuntime`

### Status
Aceita

### Contexto
A retomada da execução após uma confirmação pode depender do agente que a pediu, da topologia dos agentes, do Runner, da configuração do App e do serviço de sessão persistente. Esse comportamento é sensível a versão e configuração.

### Decisão
Isolar a integração FastAPI ↔ ADK em uma camada (`app/runtime/adk_runtime.py`, **implementada no Passo 8**) com operações:

```text
create_session()   get_session()   send_message()
get_events()       list_pending_confirmations()   resume_confirmation()
```

A camada esconde Runner, SessionService, `FunctionResponse`, `invocation_id`, retomada, parsing de eventos e agente originador; erros são de domínio (`ConfirmationNotPendingError`, `ConfirmationResumeError`, `SessionNotFoundError`), nunca HTTP. O `App` é criado com `ResumabilityConfig(is_resumable=True)`; o `user_id` do ADK é uma constante interna (chave de partição), nunca fonte de identidade — o apartamento vive em `state`, gravado na criação da sessão.

O restante da aplicação **não depende** dos detalhes internos da retomada.

### Motivos
- Concentrar em um ponto o código mais frágil e mais dependente de versão.
- Permitir trocar a estratégia de retomada sem alterar rotas ou serviços.
- Facilitar testes de integração específicos.

### Consequências
- O Runtime torna-se o ponto crítico a validar cedo ([RT-001](riscos-tecnicos.md#rt-001--tool-confirmation--sessão-persistente)).
- Detalhes do ADK não devem vazar para rotas, services ou repositories.
- Versão do ADK fixada exatamente (qualquer atualização exige reexecutar a validação da retomada).

### Alternativas consideradas
- **Chamar o Runner diretamente nas rotas FastAPI:** menos código, mas espalha a dependência do ADK pela aplicação.
- **Usar apenas as ferramentas de desenvolvimento do ADK:** não atende o contrato HTTP.

### Contrato de eventos (revisão de 13/10/2026)
`AdkRuntime.get_events` retorna eventos integrais como objetos JSON, um por evento persistido e na mesma ordem, preservando todas as partes e metadados. A projeção anterior permanece em `get_event_views` somente para diagnóstico. A rota de eventos usa `get_events`. Regressões: `tests/test_runtime_events.py` e comparação do conteúdo completo em subprocessos no teste de restart.

---

## ADR-011 — Histórico de reservas canceladas mantido

### Status
Aceita

### Contexto
Um código de reserva nunca pode ser reutilizado, nem depois de cancelamento. Se o cancelamento removesse a linha, o código poderia voltar a ser gerado.

### Decisão
Reservas canceladas **permanecem registradas** com `status = CANCELADA` (por exemplo `RSV-1234` / `CANCELADA`). A unicidade do código é garantida pelo sistema e reforçada por **constraint no banco**.

### Motivos
- Impede reutilização de códigos.
- Preserva histórico para auditoria.

### Consequências
- Consultas de "reservas do morador" devem considerar apenas reservas **ativas**, a menos que o histórico seja pedido explicitamente.
- A constraint de exclusividade por área e data vale **só para ativas** ([ADR-008](#adr-008--integridade-concorrente-garantida-pelo-banco)).
- A geração de códigos deve continuar sem repetir após reinício e levar em conta também as reservas canceladas.

### Implementação do Passo 3
- `generate_reservation_code()` usa `RSV-` + os primeiros 8 hex de UUID4, em maiúsculas. A PK de `Reserva.codigo` garante unicidade; o gerador isoladamente não a garante.
- `_insert_reservation()` tenta novamente após colisão de código, até cinco tentativas por padrão; ao esgotar, lança `ReservationCodeGenerationError`.
- O histórico cancelado permanece no banco e participa da unicidade. Os testes forçam colisão com código cancelado e esgotamento de tentativas.

### Alternativas consideradas
- **Excluir fisicamente a reserva:** rejeitada — permitiria reuso de código.
- **Marcar com flag booleana em vez de status:** funciona, mas um status explícito comporta melhor futuros estados.

---

## ADR-012 — Controle próprio de confirmações além do estado do ADK

### Status
Aceita — **implementada no Passo 8** *(quatro pontos provisórios resolvidos abaixo)*

### Contexto
O ADK oferece Tool Confirmation, mas a retomada pode falhar silenciosamente conforme topologia e sessão persistente. Além disso, é preciso garantir `409` para `id` inexistente ou já respondido, e idempotência da aprovação.

### Decisão
Além do Tool Confirmation do ADK, manter **controle explícito no backend** (tabela conceitual `confirmacoes`):

```text
id, session_id, acao, detalhes, status,
invocation_id, agent_name, created_at, responded_at
```

Estados: `PENDING`, `PROCESSING`, `APPROVED`, `REJECTED`. Regras:

- somente `PENDING` **da sessão** pode receber resposta;
- inexistente / já respondida / de outra sessão → **409**;
- confirmação respondida não executa de novo;
- aprovação executa a ação **uma única vez**;
- rejeição não altera dados de negócio.

### Motivos
- O estado de verdade para "o que está pendente" e "já foi respondido" fica no backend, sob controle do código.
- Guarda `invocation_id` e `agent_name`, informações que a retomada pode exigir (RT-002).
- Permite alimentar `confirmacoes_pendentes` na resposta da API.

### Consequências
- Há **dois** registros de pendência (ADK e backend) que precisam permanecer consistentes.
- Como a tabela fica em `condominio.db` e as sessões em `adk_sessions.db`, não há transação única entre ambos.
- A mudança de estado precisa ser **atômica** para garantir que apenas uma resposta à confirmação seja aceita.
- A atomicidade da transição impede duas respostas vencedoras, mas não garante sozinha que uma aprovação seja retomada e produza o efeito de negócio; a recuperação entre bancos e etapas precisa de desenho próprio.

### Decisões do Passo 8 (antes provisórias)
- **ID:** o `id` público é o `function_call_id` da chamada `adk_request_confirmation` (sem UUID adicional; sem mapeamento).
- **Ordem e recuperação:** `PENDING → PROCESSING` (claim atômico por `UPDATE … WHERE id AND session_id AND status='PENDING'`, `rowcount == 1`) → `FunctionResponse` ao ADK → Tool original executa → `APPROVED`/`REJECTED`. Falha técnica: volta a `PENDING` **somente** se a quantidade de eventos persistidos no ADK não mudou desde o claim (a Tool certamente não executou); caso contrário permanece `PROCESSING` (prioriza não duplicar). `PROCESSING` deixado por queda do processo não é reconciliado automaticamente — risco residual documentado em RT-001.
- **Aprovada porém recusada pelo negócio:** a confirmação fica `APPROVED` (o usuário aprovou e a tentativa foi executada); o resultado de negócio (`created`/`unavailable`) está em `ResumeResult.tool_result`. `APPROVED` ≠ reserva criada.
- **Dois bancos:** persistência separada — ADK em `adk_sessions.db` (sessão, eventos, invocation), aplicação em `condominio.db` (`confirmacoes`). Sem transação única; `list_pending_confirmations` reconcilia o caso "ADK gravou, tabela não".
- **Validação de invocation:** a retomada confere que o `invocation_id` registrado é o do evento da chamada na sessão, e o Runner resolve a invocation a partir do mesmo evento.

### Pontos ainda provisórios
- Reconciliação automática de `PROCESSING` órfão.
- Duas confirmações na mesma sessão e respostas fora de ordem têm cobertura offline em `tests/adversarial/test_confirmation_attacks.py`; Gemini continua pendente.

### Alternativas consideradas
- **Depender apenas do estado de confirmação do ADK:** rejeitada — não cobre `409`, idempotência nem o risco de retomada silenciosa.
- **Controle apenas próprio, sem usar o Tool Confirmation do ADK:** possível, mas perde o mecanismo nativo de pausa/retomada da execução.

---

## ADR-013 — Camada de Service, erros de domínio e separação request / execução confirmada

### Status
Aceita (Passo 3)

### Contexto
As regras do condomínio precisam funcionar sem LLM e sem expor detalhes de persistência.

### Decisão
- `ReservationService` e `VisitorService` (`app/services/`) concentram os casos de uso; repositories continuam só com persistência (ganharam consultas restritas ao apartamento e de existência).
- Erros de domínio em `app/domain/errors.py` (`DomainError` e derivados). Na inserção de reserva, `IntegrityError` é convertido: conflito de área/data → `AreaUnavailableError`; colisão de código → nova tentativa (máx. 5 por padrão) → `ReservationCodeGenerationError`. Isso se aplica à inserção de reserva, não constitui tradução geral de falhas de persistência. `service_session` traduz contenção nos Services de reservas e visitantes; outros erros operacionais continuam detectáveis.
- `request_*` decide (gratuito → cria; pago/visitante → `REQUIRES_CONFIRMATION`, sem gravar); `create_confirmed_*` são funções internas separadas. Não existe parâmetro `confirmed`.
- Reserva alheia é tratada como inexistente (`ReservationNotFoundError`).
- `request_reservation` também consulta disponibilidade antes de pedir confirmação (apenas UX; o banco segue sendo a garantia).
- Rejeita-se nome de visitante vazio (sanidade de entrada, `InvalidVisitorNameError`).

### Consequências
Os services gerenciam suas sessões. Na criação de reservas, a sessão de validação termina antes da sessão de inserção; cada tentativa usa uma nova sessão. No cancelamento e na autorização confirmada de visitante, validação e escrita ocorrem na mesma sessão. Portanto, a separação entre leitura e escrita não é uma propriedade de todos os casos de uso.

### Pendência do Passo 3 corrigida nesta revisão
Na auditoria de 11/10/2026, uma transação concorrente `BEGIN IMMEDIATE` mantida em SQLite temporário além de `busy_timeout=5000` fez criar reserva, cancelar reserva e autorizar visitante propagarem `sqlalchemy.exc.OperationalError` (`database is locked`). A correção em `app/services/_persistence.py` fecha a sessão e traduz contenção para `StorageBusyError`; as tools retornam `temporarily_unavailable`. A regressão em `tests/test_persistence_failures.py` cobre criação, cancelamento, visitante, ausência de efeitos parciais e recuperação após liberar o lock. Sem retry automático; banco ocupado não equivale a área ocupada.

---

## ADR-014 — Reset apaga sessões por padrão (Passo 8)

### Status
Aceita — revisa a decisão do Passo 2 (ADR-006: reset preserva `adk_sessions.db`).

### Contexto
Confirmações passaram a viver em `condominio.db`, enquanto a pendência equivalente vive nos eventos de `adk_sessions.db`. Zerar apenas o domínio deixaria sessões com `adk_request_confirmation` sem linha na tabela (e ID desconhecido é rejeitado); zerar apenas as sessões deixaria linhas órfãs.

### Decisão
`scripts/reset.py` restaura **ambos** por padrão (`condominio.db` a partir de `dados/`, incluindo `confirmacoes` vazia, e remove `adk_sessions.db`, recriado no próximo uso). `--keep-sessions` preserva as sessões; `--sessions` é aceito como no-op por compatibilidade. **RESTART** de processo nunca apaga nada. `dados/` segue somente leitura.

---

## Decisões ainda abertas (resumo)

| Tema | Onde |
|---|---|
| ~~Validação da escolha inicial `sub_agents` + transferência~~ — validada com Gemini real no Passo 12 | ADR-002 |
| ~~Revalidar contenção HTTP com Gemini~~ — aprovações simultâneas validadas no Passo 12 | ADR-008 / ADR-013 |
| Calibração da busca lexical e qualidade da resposta com Gemini (granularidade e limites já decididos) | ADR-009 |
| ~~Relação entre `id` de confirmação do backend e identificador do ADK~~ — decidido no Passo 8 (`id` = `function_call_id`) | ADR-012 |
| Recuperação automática de `PROCESSING` órfão | ADR-012 |


## ADR-015 — Recuperação de pendências também no contrato HTTP (16/10/2026)

**Status:** aceita e implementada.

Uma queda pode deixar o pedido de confirmação nos eventos ADK antes do commit no banco de domínio.
`AdkRuntime.list_pending_confirmations` reconcilia apenas chamadas sem resposta formal; o insert
idempotente preserva estados existentes. `send_message` usa essa operação para compor a lista pública;
`resume_confirmation` a chama antes do claim. IDs arbitrários ou de outra sessão continuam dando 409.
Isso não reconcilia `PROCESSING` órfão nem torna atômicos os dois bancos.

Alternativa rejeitada: exigir que o cliente invoque um método interno ou aprove outra confirmação
para disparar a recuperação. Regressão HTTP entre processos: `test_http_recovers_confirmation_missing_from_domain_after_restart`.

## ADR-016 — Limites de execução e erros HTTP seguros (Passo 11)

**Status:** aceita e implementada.

- `RunConfig(max_llm_calls=25)` limita laços do modelo. Em `/mensagens`, `AgentRunLimitError` vira 502;
  na retomada aplica-se `ConfirmationResumeError` (503 se liberada, 500 se ambígua).
- A validação devolve 422 com tipo, localização e mensagem, sem refletir o input. Isso evita que
  números não finitos quebrem a serialização JSON da resposta de erro.
- Confirmação exige booleano estrito. IDs não pendentes da sessão dão 409; sessão ausente dá 404.
- O limite de 25 requer calibração com Gemini; não é prova de qualidade dos fluxos reais.

Regressões: `tests/adversarial/test_regressions.py`. Alternativas rejeitadas: teto padrão de 500
chamadas e eco integral do corpo inválido.

## ADR-017 — Reinício normal distinto de crash nos testes (16/10/2026)

**Status:** aceita e implementada na infraestrutura de teste.

`tests.uvicorn_worker` executa o servidor real em subprocesso e aceita desligamento por stdin.
O servidor executa o lifespan de shutdown antes da leitura SQLite seguinte. Timeout causa falha
explícita e limpeza do processo; não há retry para esconder erro de disco. O ataque de crash usa
`os._exit(86)` separadamente. O cenário live usa `app.main:app` em dois processos sequenciais.
Eventos artificiais usam timestamps explícitos; empate é verificado por ID conforme ADK 2.9.1.
Não se presume ordem de inserção para timestamps iguais.

A fixture adversarial `world` é registrada em `tests/conftest.py`, no pai comum às seleções
mistas de arquivos. Continua com escopo por teste; sua lógica e os bancos temporários são
os mesmos. Isso evita falhas de descoberta da fixture ao intercalar diretórios na seleção.
