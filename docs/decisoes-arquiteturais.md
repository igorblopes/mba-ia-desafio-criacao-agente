# Decisões arquiteturais — Residencial Aurora

> **Status do documento:** ADRs simplificados registrados **antes** da implementação.
> Nada aqui está implementado. Quando uma decisão descreve algo futuro, o texto usa "planejado" ou "proposto".
> Nomes de arquivos e módulos seguem a proposta inicial de [`arquitetura.md`](arquitetura.md) e podem evoluir.

**Princípio que guia todas as decisões:**

> O modelo conduz a conversa e decide o caminho da interação, mas o código e o banco de dados decidem o que é permitido. O LLM nunca é uma barreira de segurança.

## Convenção de status

- **Aceita** — decisão tomada; mudanças futuras devem ser comparadas a ela e registradas como nova ADR ou revisão.
- **Provisória** — decisão ainda não fechada. Quando uma ADR "Aceita" tem um ponto específico em aberto, esse ponto aparece em uma subseção **Pontos provisórios** e na lista final.

## Índice

| ADR | Título | Status |
|---|---|---|
| [ADR-001](#adr-001--fastapi-como-camada-http) | FastAPI como camada HTTP | Aceita |
| [ADR-002](#adr-002--arquitetura-multiagente) | Arquitetura multiagente | Aceita (acionamento provisório) |
| [ADR-003](#adr-003--três-especialistas-além-do-agente-principal) | Três especialistas além do agente principal | Aceita |
| [ADR-004](#adr-004--agent--tool--service--repository) | Agent → Tool → Service → Repository | Aceita |
| [ADR-005](#adr-005--sqlite-como-armazenamento) | SQLite como armazenamento | Aceita |
| [ADR-006](#adr-006--bancos-separados-para-domínio-e-sessões-do-adk) | Bancos separados para domínio e sessões do ADK | Aceita |
| [ADR-007](#adr-007--identidade-obtida-exclusivamente-da-sessão) | Identidade obtida exclusivamente da sessão | Aceita |
| [ADR-008](#adr-008--integridade-concorrente-garantida-pelo-banco) | Integridade concorrente garantida pelo banco | Aceita (forma exata provisória) |
| [ADR-009](#adr-009--regulamento-consultado-sob-demanda) | Regulamento consultado sob demanda | Aceita (seleção provisória) |
| [ADR-010](#adr-010--isolamento-da-integração-adk-em-adkruntime) | Isolamento da integração ADK em `AdkRuntime` | Aceita |
| [ADR-011](#adr-011--histórico-de-reservas-canceladas-mantido) | Histórico de reservas canceladas mantido | Aceita |
| [ADR-012](#adr-012--controle-próprio-de-confirmações-além-do-estado-do-adk) | Controle próprio de confirmações além do estado do ADK | Aceita (integração provisória) |

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
Aceita *(o mecanismo de acionamento dos especialistas é **provisório**)*

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

### Pontos provisórios
- A transferência é a escolha inicial, mas sua compatibilidade com Tool Confirmation e sessão persistida ainda precisa ser comprovada no RT-001/RT-002.
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
- Se `scripts/reset.py` também apaga `adk_sessions.db` — **em aberto**.

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

### Alternativas consideradas
- **Apartamento como argumento da tool, validado contra o da sessão:** funciona, mas mantém a superfície de erro e convida a esquecer a validação em uma tool nova.
- **Identidade nas instruções do agente:** rejeitada — dependeria do prompt.

---

## ADR-008 — Integridade concorrente garantida pelo banco

### Status
Aceita *(forma exata da constraint e política de transação são decisões de implementação)*

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

### Pontos provisórios
- Forma exata (índice único parcial ou equivalente), modo de transação e política de espera/repetição quando o banco estiver ocupado.

### Alternativas consideradas
- **Verificar disponibilidade e depois gravar:** rejeitada — *check-then-act* sujeito a condição de corrida.
- **Lock em memória no processo Python:** não vale entre processos nem sobrevive a reinício; pode complementar, nunca substituir a constraint.
- **Confiar no modelo para não pedir duas vezes:** rejeitada — violaria o princípio central.

---

## ADR-009 — Regulamento consultado sob demanda

### Status
Aceita *(estratégia de seleção de trechos é provisória)*

### Contexto
O regulamento é longo. Colocá-lo nas instruções ou no histórico aumenta o custo de todas as chamadas e polui os eventos da sessão com assuntos irrelevantes. O conteúdo devolvido por tools é gravado nos eventos.

### Decisão
O regulamento completo **não** entra no prompt do agente principal, nas instruções permanentes dos agentes nem no histórico. Um **`RegulationService`** (conceitual) lê `dados/regulamento.md` e usa inicialmente a estrutura de títulos/seções e palavras-chave para localizar conteúdo, sem banco vetorial. Ele **retorna somente o trecho necessário**; esse trecho pode aparecer nos eventos. A **própria tool limita** o que devolve.

### Motivos
- Reduz tokens e custo por mensagem.
- Evita que assuntos não relacionados fiquem nos eventos.
- A limitação é feita por código, não por pedir ao modelo para "ignorar" conteúdo.

### Consequências
- A qualidade da resposta depende da qualidade da seleção do trecho.
- É preciso decidir o que fazer quando nenhum trecho relevante for encontrado (resposta de "não encontrado" em vez de devolver o documento).
- Os retornos da tool devem ter tamanho limitado e ser inspecionados nos eventos.

### Pontos provisórios
- Granularidade final (capítulo, artigo ou parágrafo), critérios de ranqueamento dentro da recuperação por estrutura/palavras-chave e limites de tamanho. A abordagem inicial está definida, mas precisa ser calibrada durante a implementação.
- Tratamento de perguntas que atravessam mais de um assunto.

### Alternativas consideradas
- **Regulamento completo no prompt do agente principal:** rejeitada — custo e poluição de contexto.
- **Regulamento completo no prompt do especialista:** rejeitada — as instruções acompanham todas as chamadas daquele agente.
- **Retornar o arquivo inteiro pela tool:** rejeitada — iria para os eventos da sessão.

---

## ADR-010 — Isolamento da integração ADK em `AdkRuntime`

### Status
Aceita

### Contexto
A retomada da execução após uma confirmação pode depender do agente que a pediu, da topologia dos agentes, do Runner, da configuração do App e do serviço de sessão persistente. Esse comportamento é sensível a versão e configuração.

### Decisão
Isolar a integração FastAPI ↔ ADK em uma camada (proposta: `app/runtime/adk_runtime.py`) com operações conceituais:

```text
create_session()
send_message()
resume_confirmation()
get_events()
```

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

### Pontos provisórios
- Formato do código e estratégia de geração (a unicidade, não o formato, é a decisão firme).

### Alternativas consideradas
- **Excluir fisicamente a reserva:** rejeitada — permitiria reuso de código.
- **Marcar com flag booleana em vez de status:** funciona, mas um status explícito comporta melhor futuros estados.

---

## ADR-012 — Controle próprio de confirmações além do estado do ADK

### Status
Aceita *(integração com o identificador do ADK é provisória)*

### Contexto
O ADK oferece Tool Confirmation, mas a retomada pode falhar silenciosamente conforme topologia e sessão persistente. Além disso, é preciso garantir `409` para `id` inexistente ou já respondido, e idempotência da aprovação.

### Decisão
Além do Tool Confirmation do ADK, manter **controle explícito no backend** (tabela conceitual `confirmacoes`):

```text
id, session_id, acao, detalhes, status,
invocation_id, agent_name, created_at, responded_at
```

Estados: `PENDING`, `APPROVED`, `REJECTED`. Regras:

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

### Pontos provisórios
- Relação entre o `id` do backend e o identificador da chamada pendente no ADK (iguais ou mapeados).
- Ordem exata entre a transição de estado, a retomada do ADK e a gravação do efeito de negócio, e como recuperar de falha entre essas etapas.
- Como registrar o resultado quando a aprovação é válida, mas a execução é recusada por conflito (por exemplo, data tomada por outro morador).

### Alternativas consideradas
- **Depender apenas do estado de confirmação do ADK:** rejeitada — não cobre `409`, idempotência nem o risco de retomada silenciosa.
- **Controle apenas próprio, sem usar o Tool Confirmation do ADK:** possível, mas perde o mecanismo nativo de pausa/retomada da execução.

---

## Decisões ainda abertas (resumo)

| Tema | Onde |
|---|---|
| Validação da escolha inicial `sub_agents` + transferência e eventual revisão | ADR-002 |
| Forma exata da constraint, modo de transação e espera sob concorrência | ADR-008 |
| Granularidade e método de seleção de trechos do regulamento | ADR-009 |
| Formato e geração do código de reserva | ADR-011 |
| Se a restauração também apaga sessões do ADK | ADR-006 |
| Relação entre `id` de confirmação do backend e identificador do ADK | ADR-012 |
| Ordem e recuperação de falhas entre confirmação, retomada e gravação | ADR-012 |
