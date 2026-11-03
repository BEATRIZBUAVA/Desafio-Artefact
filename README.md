# Lia — agente de atendimento da Empório da Música

Protótipo de agente de atendimento por mensagens de texto para a **Empório da Música**, loja (fictícia) de
instrumentos musicais em Campo Grande/MS. A Lia responde dúvidas sobre catálogo, preços, promoções,
pedidos e políticas da loja, decidindo sozinha quando consultar **dados** (CSVs) e quando consultar
**políticas** (manual em PDF).

Desafio técnico — AI Engineer, Artefact.

```
Você: Quanto custa o Takamine GD20?
  ↳ buscar_produtos({"termo": "Takamine GD20"}) -> {"resultados": [{"id": 95, "preco_tabela": 2199.0, "estoque": 5, "preco_pix": 2089.05, ...}]}
Lia: O *Takamine GD20 Dreadnought Natural* sai por R$ 2.199,00 e temos 5 unidades. No PIX fica R$ 2.089,05 ...
```

## Sumário
- [Como rodar](#como-rodar)
- [Arquitetura](#arquitetura)
- [Decisões técnicas](#decisões-técnicas)
- [Tratamento de dados e suposições](#tratamento-de-dados-e-suposições)
- [Exemplos de conversa](#exemplos-de-conversa)
- [Testes](#testes)
- [Limitações e próximos passos](#limitações-e-próximos-passos)
- [Uso de assistentes de código](#uso-de-assistentes-de-código)

## Como rodar

Pré-requisitos: Python 3.10+ e uma chave **gratuita** da API do Gemini
([Google AI Studio → Get API key](https://aistudio.google.com/apikey)).

```bash
git clone https://github.com/BEATRIZBUAVA/Desafio-Artefact.git
cd Desafio-Artefact
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # e coloque sua GEMINI_API_KEY no .env
```

Conversar pela linha de comando:

```bash
python -m emporio                 # nova conversa
python -m emporio --debug         # mostra cada ferramenta chamada e o que ela devolveu
python -m emporio --sessao ana    # retoma a conversa "ana" (o histórico fica em data/conversas.db)
```

Dentro do chat: `/debug` liga/desliga o rastro de ferramentas, `/limpar` apaga o histórico da sessão, `/sair` encerra.

Outros comandos:

| Comando | O que faz |
|---|---|
| `pytest` | Testes das ferramentas e do loop do agente (não usam a API, rodam offline) |
| `python scripts/gerar_exemplos.py` | Roda os 5 cenários contra o modelo real e regrava `exemplos/*.md` |
| `python scripts/relatorio_qualidade.py` | Lista as inconsistências encontradas nos CSVs |
| `python scripts/extrair_politicas.py` | Extrai o texto bruto do PDF de políticas |

Variáveis de ambiente (`.env`):

| Variável | Uso |
|---|---|
| `GEMINI_API_KEY` | Obrigatória |
| `GEMINI_MODEL` | Modelo principal (padrão `gemini-3.6-flash`) |
| `GEMINI_FALLBACK_MODELS` | Modelos tentados, em ordem, se o principal estiver sem cota ou sobrecarregado |
| `EMPORIO_AGORA` | Opcional, ex. `2026-11-08T11:20`: fixa a data/hora "atual" para testar horário da loja e prazos |

> **Cota do plano gratuito:** hoje o Gemini gratuito permite cerca de **20 requisições por dia por modelo**,
> e cada mensagem do cliente gasta de 1 a 3 requisições (ferramentas + resposta). Quando a cota de um modelo
> acaba, o agente passa sozinho para o próximo da lista de fallback, já que cada modelo tem a sua própria cota.

## Arquitetura

```
Cliente ──► CLI (__main__.py) ──► Agente (agent.py) ◄──► Gemini (function calling)
                                     │   ▲
                       histórico     │   │ resultado (JSON)
                    SQLite (memory)  ▼   │
                                  Ferramentas (tools.py) — Python determinístico
                     ┌──────────────┬──────────────┬───────────────┬──────────────┐
                     │ catálogo     │ pedidos      │ políticas     │ loja         │
                     │ buscar_      │ consultar_   │ consultar_    │ info_loja    │
                     │ produtos,    │ pedido,      │ politicas     │ (horário,    │
                     │ detalhes_    │ listar_      │ (por tópico)  │ aberta agora)│
                     │ produto,     │ pedidos_     │               │ registrar_   │
                     │ simular_     │ cliente      │               │ solicitacao  │
                     │ pagamento    │              │               │              │
                     └──────┬───────┴──────┬───────┴───────┬───────┴──────────────┘
                            ▼              ▼               ▼
                     data/raw/*.csv (pandas, em memória)   data/politicas.md
```

```
src/emporio/
  data.py       carga e tratamento dos CSVs; regras de promoção, disponibilidade e identificação de cliente
  policies.py   seções do manual de políticas, consultáveis por tópico
  clock.py      fuso de Campo Grande, expediente, feriados, "a loja está aberta agora?"
  tools.py      as 8 ferramentas + declarações (JSON Schema) enviadas ao modelo
  prompt.py     persona e regras do prompt de sistema
  agent.py      loop de function calling com o Gemini, retentativas, persistência
  memory.py     histórico de conversa por sessão em SQLite
  __main__.py   CLI
data/
  raw/          arquivos originais fornecidos pela loja (intocados)
  politicas.md  manual revisado e dividido por tópico (fonte usada pelo agente)
  processed/    texto bruto extraído do PDF e relatório de qualidade
scripts/        extração do PDF, relatório de qualidade, geração dos exemplos
exemplos/       5 conversas reais com o agente
tests/          testes offline
```

Fluxo de uma mensagem: o agente carrega o histórico da sessão e envia a conversa + as declarações das
ferramentas ao Gemini. Se o modelo pedir ferramentas, elas rodam em Python e o resultado volta ao modelo,
até 6 rodadas. A resposta final em texto vai ao cliente, e tudo (inclusive as chamadas de ferramenta) é
salvo no SQLite.

## Decisões técnicas

### Abordagem: function calling com ferramentas determinísticas (sem RAG vetorial, sem agente de SQL)

O que a loja precisa responder se divide em dois tipos:

1. **Dados estruturados que mudam** (preço, estoque, promoção, pedido): exigem precisão total. O manual diz
   que informação errada "pode configurar propaganda enganosa". Por isso essas respostas vêm de **funções
   Python que filtram os dados e já aplicam as regras de negócio**:
   - qual promoção está ativa;
   - que o PIX não acumula com promoção;
   - que produto descontinuado não é ofertado;
   - os prazos de devolução calculados para hoje;
   - o parcelamento mínimo por faixa.

   O LLM recebe o resultado pronto e só precisa comunicar, sem fazer contas nem interpretar tabelas.
2. **Texto de políticas**: consultado por tópico (ver Retrieval).

Alternativas descartadas:
- **Agente de SQL (text-to-SQL):** flexível, mas o modelo poderia escrever uma consulta que ignora
  `is_active` da promoção ou mostra o pedido de outro cliente. Com ferramentas fechadas, as regras e a
  privacidade (LGPD) ficam garantidas no código, não dependem do prompt.
- **Frameworks (LangChain, LlamaIndex, LangGraph):** para 8 ferramentas e um loop simples, o SDK oficial
  do Gemini basta e deixa o fluxo explícito e fácil de depurar. O loop de ferramentas é **manual** (o
  function calling automático do SDK está desligado). Assim registro cada chamada (modo `--debug` e
  exemplos), limito as rodadas e persisto o histórico completo.

**Quando o agente consulta o quê** é decidido pelo modelo, guiado pelas descrições das ferramentas e por
regras explícitas no prompt. Por exemplo, "nunca informe preço sem consultar" e "para devolução, consulte o
pedido E a política `trocas_devolucoes`".

### Modelo e provedor: Gemini Flash (plano gratuito), com fallback entre modelos

- Gratuito no Google AI Studio, o que deixa o projeto reproduzível pelo avaliador sem custo.
- A família Flash é boa em function calling e em português, com latência baixa, o que importa num chat tipo
  WhatsApp.
- Principal: `gemini-3.6-flash`.
  - O plano inicial era o `gemini-2.5-flash`, mas a API respondeu que ele não está mais disponível para chaves
    novas.
  - O `gemini-3.8-flash` estava com erro 503 (alta demanda) durante o desenvolvimento.
- Mantive a temperatura padrão, como recomendado para a família Gemini 3.
- **Resiliência:** no plano gratuito, 429 (cota) e 503 (sobrecarga) foram os erros mais comuns. O agente tenta
  de novo com espera crescente e, se não der, passa para o próximo modelo de `GEMINI_FALLBACK_MODELS` e fica
  nele pelo resto da sessão.
- Trocar de modelo é só mudar `GEMINI_MODEL`. As ferramentas e as regras de negócio não dependem do modelo.

### Retrieval das políticas: por tópico, sem embeddings

O manual tem 8 páginas e 9 seções bem separadas: sobre, horário, pagamento, trocas e devoluções, frete,
promoções, atendimento, garantia e privacidade. Com um corpus desse tamanho, busca vetorial adicionaria
complexidade (modelo de embedding, chunking, limiar de similaridade) sem ganho. Ela também pode errar trazendo
um trecho "parecido". Em vez disso:
- o PDF foi convertido em `data/politicas.md`, uma seção `##` por tópico;
- a ferramenta `consultar_politicas` recebe o tópico por **enum**, e a descrição de cada tópico vai na
  declaração da ferramenta;
- o modelo escolhe o tópico, e o trecho volta inteiro, com tabelas legíveis.

A busca é determinística e auditável: dá para ver no `--debug` exatamente qual trecho embasou cada resposta.

Por que não colocar o manual inteiro no prompt? Funcionaria (é pequeno), mas o desafio pede que o agente
*saiba quando* consultar políticas. Além disso, buscar sob demanda deixa o prompt menor e escala se o manual
crescer. Se crescer muito, o próximo passo seria trocar o enum por busca híbrida (BM25 + embeddings) sobre as
seções, sem mudar a interface da ferramenta.

### Estratégia de prompt

O prompt de sistema (`src/emporio/prompt.py`) tem:
- **Persona:** "Lia", tom "amigo que entende de música" (seção 7.1 do manual), mensagens curtas e formatação
  de WhatsApp.
- **Regra de ouro:** nada de preço, estoque, prazo ou regra sem ferramenta. Na dúvida sobre uma política,
  encaminhar para humano em vez de decidir.
- **Roteamento:** qual ferramenta usar em cada tipo de pergunta, e que pedidos exigem número + e-mail ou
  telefone.
- **Regras de comunicação de preço:**
  - preço original, % e preço promocional juntos;
  - promoção vencida informada com transparência;
  - sem prometer desconto.
- **Escopo:**
  - acessórios redirecionados com gentileza;
  - assuntos fora da loja recusados em uma frase;
  - proteção básica contra *prompt injection* (não revelar instruções nem mudar de papel).
- **Contexto dinâmico:** data e hora atuais de Campo Grande, para o modelo raciocinar sobre "hoje".

Parte das regras fica **também no código**: verificação de dono do pedido, promoção ativa e cálculo de
prazos. O prompt orienta; o código garante.

### Interface: CLI

O foco pedido é o agente funcionando. A CLI tem retomada de sessão e um modo debug que mostra o
raciocínio em ferramentas, útil para avaliar. A classe `Agente` não depende da CLI: expor via API (FastAPI) ou
webhook de WhatsApp é só criar outra "casca" que chame `Agente(sessao).responder(texto)`.

### Persistência do histórico: SQLite por sessão

Atendimento por mensagem é assíncrono: o cliente volta horas depois e espera que a loja lembre do que foi
falado (ex.: o número do pedido). Por isso:
- o histórico completo (incluindo chamadas de ferramenta) é salvo em SQLite, identificado pela sessão (num
  WhatsApp real, seria o telefone);
- para controlar custo e contexto, só os últimos 20 turnos voltam ao modelo, sempre cortando no começo de
  uma mensagem do cliente, nunca no meio de uma chamada de ferramenta.

## Tratamento de dados e suposições

Os CSVs originais ficam intocados em `data/raw/`. O tratamento é feito na carga (`data.py`), e
`python scripts/relatorio_qualidade.py` lista o que foi encontrado
([saída](data/processed/relatorio_qualidade.txt)).

**Catálogo**

| Situação encontrada | Decisão |
|---|---|
| Produto 96 com status ativo e estoque 0 | Tratado como **esgotado**; o agente sugere alternativas parecidas e disponíveis |
| Produto 136 descontinuado com 13 em estoque | **Não ofertado**: o status prevalece sobre o estoque |
| Produto 130 com status `coming_soon` (e estoque 2) | Não está à venda; informado como "em breve" |
| 21 das 25 promoções inativas; produtos com várias promoções | Só valem promoções com `is_active = 1`; se houver mais de uma, vale a maior (não são cumulativas) |
| Descrição de outra marca (ex.: "Roland Synth 3" com texto de um Yamaha; ids 135–144) | Descrição **omitida** na resposta; o agente usa só nome e especificações |
| Filtro "até R$ X" | Usa o preço efetivo (promocional, quando houver) |

**Pedidos**

| Situação encontrada | Decisão |
|---|---|
| Pedidos 3 e 20 com total diferente da soma dos itens a preço atual | Exibimos o total registrado (o preço pode ter mudado depois da compra) |
| Pedidos sem data real de recebimento | Os prazos de arrependimento e garantia contam a partir de `estimated_delivery` (**suposição**) |
| Pedido 8 "enviado" com previsão vencida há meses | A ferramenta sinaliza o atraso e o agente oferece abrir chamado |
| Pedido é dado pessoal | Exige número do pedido + e-mail ou telefone do dono. Pedido inexistente e pedido de outra pessoa recebem a **mesma** resposta, para não confirmar dados de terceiros |

**Manual de políticas**

| Situação encontrada | Decisão |
|---|---|
| Dois números de telefone: 3341-4444 (dados da empresa) e 3321-4500 (seção de WhatsApp) | 3341-4444 como telefone e 3321-4500 como WhatsApp: a seção específica do canal prevalece |
| E-mail grafado com e sem acento | Adotada a forma sem acento, que é um domínio válido |
| Parcela mínima: a tabela diz R$ 100; a seção 3.1 diz R$ 50 até 3x, R$ 80 de 4x a 6x e R$ 100 de 7x a 12x | Adotada a seção 3.1, por ser a regra mais específica |
| "Mais de 300 instrumentos", mas o CSV tem 65 | O agente fala só do que existe no CSV |
| "Sugerir lojas parceiras", mas nenhuma é listada | O agente diz que não tem lista de parceiras e não inventa nomes |
| Cancelamento de pedido não é coberto | Encaminhado para atendimento humano |

**Horário:** o manual só diz "feriados". O agente considera os feriados nacionais, mais o aniversário de
Campo Grande (26/08) e a criação do Estado de MS (11/10).

## Exemplos de conversa

Gerados com `scripts/gerar_exemplos.py` contra o modelo real. As mensagens do cliente são roteirizadas e as
respostas são as que o agente deu, sem edição. Cada arquivo mostra também as ferramentas chamadas e o modelo
usado:
- os cenários 01 e 02 rodaram no `gemini-3.6-flash`;
- os cenários 03 a 05 rodaram no `gemini-3.5-flash-lite`, porque a cota diária gratuita dos modelos Flash
  acabou durante o desenvolvimento.

O fato de o comportamento se manter num modelo menor é um bom sinal de que as regras estão nas ferramentas e
não dependem do modelo.

Bugs que os exemplos revelaram e que foram corrigidos antes da versão final:
- a listagem de pedidos não trazia o alerta de atraso;
- o agente pedia os dados do "amigo" em vez de orientar o titular a entrar em contato;
- num domingo, o agente não dizia quando a loja reabre.

Ficou um deslize menor no 04: o modelo chamou a data da compra de "data de envio".

| Arquivo | Cenário | O que demonstra |
|---|---|---|
| [01_catalogo_violoes](exemplos/01_catalogo_violoes.md) | "Violões até R$1000?" + parcelamento | Filtro por categoria e preço, regras de parcela mínima e PIX |
| [02_preco_promocao_estoque](exemplos/02_preco_promocao_estoque.md) | Preço do Takamine GD20, promoção vencida, produto esgotado | Transparência sobre promoção expirada; alternativas ao esgotado |
| [03_devolucao_arrependimento](exemplos/03_devolucao_arrependimento.md) | "Me arrependi, posso devolver?" | Verificação de identidade, política + dados do pedido + data de hoje → prazos vencidos, caminho da garantia do fabricante |
| [04_status_pedido_e_privacidade](exemplos/04_status_pedido_e_privacidade.md) | Pedido sem número; pedido "de um amigo" | Busca por telefone, rastreio, atraso detectado, recusa de dados de terceiros (LGPD) |
| [05_fora_do_escopo_e_loja](exemplos/05_fora_do_escopo_e_loja.md) | Acessórios, redação escolar, prompt injection, "dá pra passar aí hoje?" num domingo | Escopo, segurança e horário em tempo real |

## Testes

`pytest` roda 17 testes offline:
- **Ferramentas:** preço exato, filtro de disponibilidade, esgotado com alternativas, promoção ativa vs.
  expirada, PIX não cumulativo, parcelamento por faixa, verificação de dono do pedido, prazos vencidos,
  horário/feriados, descrições inconsistentes, alerta de atraso e aviso quando a busca corta resultados.
- **Loop do agente com um cliente Gemini falso:** ferramenta → resposta → histórico persistido e retomado;
  fallback para resposta vazia; validade das declarações.

Assim as regras de negócio ficam testadas sem depender do modelo nem gastar cota da API.

## Limitações e próximos passos

**Limitações conhecidas**
- **Avaliação:** os testes cobrem as ferramentas, não a qualidade das respostas do LLM. Com mais tempo, criaria
  um conjunto de avaliação (perguntas + critérios: ferramenta certa chamada, preço correto citado, recusa
  quando deve) e usaria LLM-as-judge para medir regressões a cada mudança de prompt ou modelo.
- **Busca de produtos:** é por palavras do nome (com tolerância a acento e plural). Pedidos subjetivos ("um violão
  bom pra fingerstyle") dependem do modelo combinar categoria e especificações. Busca semântica sobre descrição e
  specs ajudaria.
- **Dados lidos de CSV em memória:** num cenário real, as ferramentas consultariam o ERP ou banco via API, e
  a interface das ferramentas não mudaria.
- **Data de recebimento:** usamos a previsão de entrega como aproximação.
- **Solicitações:** reclamações e pedidos de atendimento humano vão para `data/solicitacoes.jsonl`. Faltaria
  integrar com o sistema de tickets da loja e notificar a equipe.
- **Identificação do cliente:** é por e-mail ou telefone digitado. No WhatsApp real, o próprio número do
  remetente identificaria o cliente.
- **Free tier do Gemini:** são cerca de 20 requisições por dia por modelo. O fallback entre modelos
  ameniza, mas uma sessão longa de testes pode esgotar todos. Em produção, o caminho é o plano pago.
- **Interface:** só CLI.

**Com mais tempo**
- Integração com WhatsApp (webhook da Cloud API) e uma API FastAPI.
- Guardrails de saída: checar se todo preço citado na resposta apareceu num resultado de ferramenta.
- Streaming de resposta e observabilidade: tracing das chamadas de ferramenta, custo e latência por conversa.
- Handoff real para humano com resumo automático da conversa.
- Mensagem automática fora do expediente, como o manual prevê.

## Uso de assistentes de código

Usei o **Claude Code** (modelo Claude Opus) como par de programação durante todo o desafio. O fluxo foi:

1. **Entendimento:** pedi ao Claude que lesse o enunciado, o PDF de políticas e os CSVs e listasse requisitos e
   possíveis "pegadinhas" nos dados (contradições do manual, estoque/status, promoções inativas). Revisei essa
   lista e decidi o tratamento de cada ponto (tabela acima).
2. **Decisões de arquitetura:** discutimos as alternativas. Eu escolhi o Gemini pelo plano gratuito, e
   optamos por function calling com ferramentas fechadas em vez de text-to-SQL e por retrieval por tópico em
   vez de embeddings, pelos motivos descritos acima.
3. **Implementação incremental:** o Claude escreveu o código módulo a módulo, e cada etapa virou um commit
   (veja o histórico). Os testes foram escritos junto e pegaram bugs reais. Exemplo: a busca por um produto
   esgotado ("Giannini GF-3D") devolvia outro modelo parecido como se fosse ele. A correção foi calcular a
   relevância antes do filtro de disponibilidade.
4. **Validação:** rodei a CLI e os cenários de exemplo contra o modelo real, li as respostas e ajustei prompt e
   ferramentas onde o comportamento não seguia a política.

A ferramenta acelerou a escrita do código e a varredura dos dados. As decisões de produto (o que fazer com cada
inconsistência, quais regras ficam no código vs. no prompt, escopo do protótipo) foram revisadas e tomadas
por mim.
