# Plano: controle de fluxo do agente com LangGraph

Branch: `feature/langchain-agents` · Data: 2026-10-31

## 1. Como funciona hoje (mapeamento)

```
message_processor.process_message / process_ide_message
  └─ autonomous_loop.execute_autonomous_loop      ← loop externo (AUTONOMOUS_MODE, máx. 20)
       └─ llm_router.invoke_llm_with_fallback     ← tenta modelos em ordem (fallback)
            └─ llm_router.route_llm_call
                 └─ lc/runner.run_langchain_llm   ← loop interno: AgentExecutor (langchain_classic)
                      └─ create_tool_calling_agent + tools (lc/tools_lc.py)
```

- **Loop interno** (`agent/lc/runner.py`): `AgentExecutor` do pacote `langchain_classic`, que é
  a API antiga e descontinuada. Ele chama o modelo e as ferramentas até o modelo parar de pedir
  ferramentas ou até `agent_max_iterations`.
- **Saída**: o modelo precisa terminar com um JSON (`AgentResponse` em `agent/lc/outputs.py`):
  `user_prompt`, `execution_plan`, `llm_response`, `is_the_user_request_completely_satisfied`,
  `critical_system_failure`. O contrato é imposto pela API de alguns provedores ou escrito no
  prompt para os outros (`prompt_builder.py`, `llm_router._with_prompt_contract`).
- **Loop externo** (`agent/autonomous_loop.py`): lê o JSON. Se `satisfied` não for `true`, reenvia
  ao modelo uma mensagem genérica ("Your response does not completely answer… try again") e
  repete até o limite.

### Problemas desse desenho

1. **O modelo corrige a própria prova.** Quem responde também decide se terminou. É comum ele
   marcar `true` cedo demais ou `false` sem motivo.
2. **Um único booleano não diz o que fazer.** Não há como dizer "falta X", "preciso perguntar algo
   ao usuário" ou "tentei e não dá". Qualquer coisa diferente de `true` vira um "tente de novo"
   genérico, que gasta chamadas e às vezes repete o mesmo erro.
3. **Pedir uma pergunta ao usuário vira loop.** O `SATISFIED_RULE` do prompt tenta remediar isso
   com texto, mas é frágil.
4. **JSON + ferramentas na mesma chamada.** Exigir o contrato JSON na resposta final atrapalha o
   uso de ferramentas em vários provedores (por isso existem `schema_enforced_by_api`,
   `_parse_json_response` com 3 estratégias, `_answer_after_limit` etc.).
5. **Dois loops aninhados com estados separados.** O externo só enxerga o texto final; não sabe
   quais ferramentas rodaram nem os resultados delas.
6. **`AgentExecutor` é legado.** No LangChain 1.x o caminho oficial é o LangGraph
   (`langgraph 1.2.14` já está instalado no `.venv`, só falta declará-lo no `requirements.txt`).

## 2. Conceitos em 1 minuto

- **LangChain**: biblioteca de peças (modelos, ferramentas, prompts). Já está em uso.
- **Agente**: um modelo em loop que decide chamar ferramentas até ter a resposta.
- **LangGraph**: forma de descrever o fluxo do agente como um **grafo**:
  - **State**: um dicionário tipado que todas as etapas compartilham (mensagens, plano,
    iteração, veredito…).
  - **Nós (nodes)**: funções Python que recebem o state e devolvem alterações.
  - **Arestas condicionais**: funções que olham o state e escolhem o próximo nó.
  - Tem limite de passos (`recursion_limit`), streaming de eventos e, se quisermos,
    persistência (checkpoint) e pausa para o humano (`interrupt`).
- `langchain.agents.create_agent` (LangChain 1.x) é um agente com ferramentas pronto,
  construído sobre o LangGraph. Ele substitui o `AgentExecutor`.

## 3. Proposta: grafo planejar → executar → avaliar

```
          ┌──────────┐
 START ──▶│ planner  │  (opcional, por config) gera plano curto estruturado
          └────┬─────┘
               ▼
          ┌──────────┐   chamadas de ferramenta
          │ executor │◀──────────────┐  (create_agent: modelo ⇄ tools)
          └────┬─────┘               │
               ▼                     │
          ┌──────────┐  needs_more_work + instrução específica
          │evaluator │───────────────┘
          └────┬─────┘
   done / needs_user_input / failed / limite atingido
               ▼
          ┌──────────┐
          │ finalize │  monta o texto final para o usuário
          └────┬─────┘
               ▼
              END
```

### State (`agent/lc/graph/state.py`)

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # conversa + tool calls
    user_request: str
    plan: list[str] | None
    draft_answer: str            # última resposta do executor (texto livre)
    verdict: Verdict | None
    iteration: int
    tool_calls: int
```

### Veredito estruturado (substitui o booleano)

```python
class Verdict(BaseModel):
    status: Literal["done", "needs_more_work", "needs_user_input", "failed"]
    reason: str                  # por que chegou nesse status
    missing: list[str] = []      # o que ainda falta, quando needs_more_work
    next_instruction: str | None # orientação concreta para a próxima rodada
```

### Nós

| Nó | O que faz | Modelo |
|---|---|---|
| `planner` | Para pedidos de várias etapas, gera `plan: list[str]`. Desligado para conversas simples. Substitui o campo `execution_plan` e continua mostrando o "📋 Execution Plan". | Configurável (pode ser um modelo barato) |
| `executor` | `create_agent(model, tools, system_prompt)` com as ferramentas atuais. **Responde em texto livre, sem contrato JSON.** | Modelo atual do worker, com fallback |
| `evaluator` | Recebe pedido, plano, ferramentas usadas com seus resultados (resumidos) e a resposta. Devolve um `Verdict` via `with_structured_output`. | Configurável (pode ser um modelo barato) |
| `finalize` | Escolhe o texto final: a resposta, a pergunta ao usuário ou uma mensagem de falha amigável. | Sem LLM |

### Roteamento

- `done` → `finalize`
- `needs_user_input` → `finalize` (a resposta é a pergunta; acaba com o loop de "pergunta ao usuário")
- `failed` → `finalize` (equivale ao `critical_system_failure`)
- `needs_more_work` e `iteration < AUTONOMOUS_MODE` → `executor`, com uma mensagem específica
  montada de `missing` + `next_instruction` (em vez do "try again" genérico)
- limite atingido → `finalize` com a melhor resposta disponível

## 4. O que se mantém

- `invoke_llm_with_fallback` e a ordem de modelos: o nó `executor` chama o modelo por meio do
  mesmo fallback (ou envolvemos o chat model com `.with_fallbacks()`).
- `FeedbackCallbackHandler`: feedback ⚙️/⏳, contagem de tokens, `/stop` (passado em
  `config={"callbacks": [...]}`, que o LangGraph propaga para os nós).
- `build_lc_tools`, filtro de relevância de ferramentas, RAG de histórico, poda de contexto.
- Formato da resposta para `message_processor` (string final): nada muda para WhatsApp/IDE.

## 5. Fases de implementação

Cada fase fica atrás de uma configuração `AGENT_FLOW = legacy | graph` (padrão `legacy` até a
fase 4), no mesmo estilo do `LLM_STACK`.

1. **Base do grafo, sem mudar o comportamento**
   - Adicionar `langgraph` ao `requirements.txt`.
   - Criar `agent/lc/graph/` (`state.py`, `nodes.py`, `build.py`).
   - Trocar `AgentExecutor` por `create_agent` dentro do `executor`, com a mesma saída,
     callbacks, `/stop`, retry 429/503 e tratamento de `max_iterations`.
   - Testes: portar os casos de `tests/test_lc_runner.py` para o novo executor.
2. **Evaluator + Verdict**
   - Nó `evaluator` com saída estruturada; roteamento pelos 4 status.
   - Remover o contrato JSON da resposta do executor quando `AGENT_FLOW=graph`
     (prompt sem o bloco do JSON e sem `response_format`).
   - Feedback "🔄 Agent reflecting" passa a mostrar o motivo (`reason`).
   - Testes com modelo falso (`FakeMessagesListChatModel`) cobrindo cada rota e o limite.
3. **Planner**
   - Nó `planner` opcional (`AGENT_PLANNER=off|auto|always`); `auto` usa uma heurística simples
     ou o próprio evaluator para decidir.
   - Plano entra no state e no prompt do executor; o evaluator confere item a item.
4. **Configuração e UI**
   - Campos em Configurações Avançadas: fluxo, modelo do evaluator/planner, limite de rodadas.
   - Registro em `llm_usage` separado por nó (`executor`, `evaluator`, `planner`).
   - Mudar o padrão para `graph` depois de validar em produção.
5. **Depois (opcional)**
   - Checkpointer SQLite (`langgraph-checkpoint-sqlite`) para retomar uma execução interrompida.
   - `interrupt()` para confirmação humana antes de ferramentas perigosas.
   - Remover `autonomous_loop` e o contrato JSON legado.

## 6. Riscos e pontos de atenção

- **Custo/latência**: o evaluator acrescenta uma chamada por rodada. Mitigação: usar um modelo
  barato e pular o evaluator quando não houve chamada de ferramenta e a resposta é conversa simples.
- **Provedores sem saída estruturada** (ollama, nvidia, cloudflare): o evaluator precisa de um
  fallback que pede JSON no prompt e reaproveita `_parse_json_response`.
- **Gemini**: confirmar que `create_agent` respeita as declarações `gemini_safe` de `tools_lc.py`.
- **Grupos do WhatsApp**: a regra de manter ferramentas de WhatsApp só em chats de WhatsApp
  (commit `abd7747`) e a regra contra "ações alegadas" passam a ser verificadas também pelo evaluator.

## 7. Decisões em aberto

1. O evaluator usa o mesmo modelo do worker ou um modelo separado (mais barato)?
2. O planner deve ser ligado por padrão para o IDE e desligado para o WhatsApp?
3. Podemos remover o contrato JSON da resposta já na fase 2 ou mantê-lo por um tempo em paralelo?
