# Estresse contrafactual do gate e canonização de proposições

**Trilha experimental com LLM, sem nova anotação humana.** Os dois experimentos usam somente o gold humano já existente (18 pares do piloto + 29 da expansão = 47). Nenhum arquivo de gold, consenso ou previsão anterior foi alterado. Rodada executada em 2026-09-28 na DeepInfra: 857 chamadas, custo real **US$ 0,33** (`usage.estimated_cost`).

Modelos:
- **Avaliados** (prompts v1 congelados, sem alteração): Qwen2.5-72B-Instruct e Llama-3.3-70B-Instruct-Turbo.
- **Gerador:** DeepSeek-V3.1.
- **Verificador / juiz:** Qwen3-235B-A22B-Instruct-2507.

Gerador e verificador não são modelos avaliados. Os IDs e preços foram confirmados no endpoint de modelos antes da execução.

## 1. Estresse contrafactual

### Por que

O gold não tem nenhum `STANCE_REVERSED`. Sem essa classe, não é possível medir se o gate evita falsas reversões **sem perder as verdadeiras**, que é a hipótese central do projeto.

### Desenho

O lado B (posterior) de cada par do gold é reescrito pelo gerador. A relação esperada é consequência da operação aplicada a um par com rótulo humano; ela não vem de um novo julgamento humano. Por isso fica registrada como `SYNTHETIC_EXPECTED`.

| Operação | Pares de origem | Esperado | Mede |
|---|---|---|---|
| `REVERSE_ON_COMPARABLE` | 12 MAINTAINED | REVERSED | recall de reversão |
| `REVERSE_ON_INCOMPARABLE` | 31 INCOMPARABLE | INCOMPARABLE | falsa reversão quando a stance muda em par incomparável |
| `NEGATED_PARAPHRASE` | 12 MAINTAINED | MAINTAINED | falsa reversão causada só pela polaridade da frase |
| `SHIFT_PROPOSITION` | 12 MAINTAINED | INCOMPARABLE | falsa comparabilidade (negativo difícil) |

Uma reescrita só entra na avaliação se passar em todas as checagens:
- **checagem determinística** de edição local: similaridade de palavras entre 0,50 e 0,995, e comprimento entre 0,6× e 1,5×;
- **verificador**, que precisa responder YES para quatro perguntas: operação cumprida, resto preservado, coerência interna e naturalidade;
- **stance esperada** sobre a proposição original, também julgada pelo verificador.

### Funil

| Operação | Planejadas | Aceitas |
|---|---:|---:|
| REVERSE_ON_COMPARABLE | 12 | 7 |
| NEGATED_PARAPHRASE | 12 | 7 |
| SHIFT_PROPOSITION | 12 | 8 |
| REVERSE_ON_INCOMPARABLE | 31 | 17 |

Motivos de rejeição mais comuns (um mesmo caso pode ter vários):
- stance diferente da esperada: 18;
- resto não preservado: 14;
- incoerência interna: 13;
- mudança insuficiente: 11. São 4 textos praticamente idênticos ao original e 7 edições mínimas em falas longas, cortadas pelo limite de 0,995 fixado antes da rodada.

### Resultados

Os valores são `k/n` de reescritas aceitas, com IC de Wilson 95% em `stress_metrics.json`. Condições: **A** = end-to-end; **B** = estruturado com comparabilidade forçada (sem gate); **C** = estruturado com gate.

| Métrica | Qwen A | Qwen B | Qwen C | Llama A | Llama B | Llama C |
|---|---:|---:|---:|---:|---:|---:|
| Recall de reversão (REVERSE_ON_COMPARABLE) ↑ | **4/7** | 3/7 | 1/7 | 3/7 | **4/7** | 0/7 |
| Falsa reversão (REVERSE_ON_INCOMPARABLE) ↓ | 2/17 | 3/17 | **1/17** | 1/17 | 5/17 | **0/17** |
| Falsa reversão (NEGATED_PARAPHRASE) ↓ | 0/7 | 1/7 | 0/7 | 0/7 | 0/7 | 0/7 |
| Falsa comparabilidade (SHIFT_PROPOSITION) ↓ | 8/8 | 7/8 | **4/8** | 8/8 | 8/8 | **2/8** |

### Leitura

1. **O gate faz o que a hipótese previa com falsas reversões.** Quando a stance muda num par incomparável, a comparação sem gate (B) emite 3/17 e 5/17 reversões falsas; com o gate (C), 1/17 e 0/17.
2. **O gate também elimina as reversões verdadeiras.** O recall de reversão cai de 3–4/7 (B) para 1/7 e 0/7 (C).
   - Nos pares transformados em reversão, os modelos passam a responder `same_proposition=NO` (Qwen 5/7, Llama 6/7), embora a proposição seja a mesma.
   - Na leitura por par, o Qwen previa MAINTAINED para 4 desses pares originais; depois da reversão, 3 viram INCOMPARABLE.
   - **O gate automático confunde "mudou a posição" com "mudou a proposição".** É um modo de falha novo e mensurável: o componente que deveria proteger contra falsas reversões também filtra as reversões reais.
3. **O end-to-end (A) não distingue proposição deslocada.** Em SHIFT_PROPOSITION, A mantém `STANCE_MAINTAINED` em 8/8 nos dois modelos. O gate (C) detecta parte dos casos (4/8 e 2/8), mas parte deles já era INCOMPARABLE no par original.
4. **Negação na frase não gera falsa reversão.** Com 7 casos, o teto do IC é de ~35%.
5. **Mesmo sem gate, a extração de stance perde parte das inversões.** Em B, 3 dos 7 pares invertidos continuam `FAVOR/FAVOR` nos dois modelos.
   - Num caso curto e limpo (mercados digitais, 1.248 caracteres), o Llama ainda leu FAVOR depois de uma inversão explícita.

**Síntese:** A e C falham de formas opostas. A reconhece reversões, mas trata qualquer par do mesmo tema como comparável. C evita falsas reversões e detecta proposições diferentes, mas descarta as reversões verdadeiras como incomparáveis. Nenhum dos dois resolve a tarefa; a ablação B mostra que o gargalo está na decisão de comparabilidade, e não só na leitura de stance.

### Qualidade das reescritas (análise pós-hoc)

Ao inspecionar as reescritas, apareceram erros de cópia em falas longas, por exemplo "atução" e "estunho". O verificador não os detectou. Um diagnóstico, adicionado depois da rodada, marca os parágrafos alterados só marginalmente (similaridade de caracteres > 0,985): 10 das 39 reescritas aceitas têm pelo menos um parágrafo assim.

Excluindo esses 10 casos, o padrão se mantém:

| Métrica | Qwen A / B / C | Llama A / B / C |
|---|---|---|
| Recall de reversão | 4/6, 3/6, 1/6 | 3/6, 4/6, 0/6 |
| Falsa reversão em incomparáveis | 1/12, 2/12, 0/12 | 0/12, 4/12, 0/12 |
| Falsa comparabilidade (SHIFT) | 5/5, 4/5, 2/5 | 5/5, 5/5, 1/5 |

O diagnóstico não é critério de aceitação, porque não foi definido antes da rodada. As 7 edições mínimas rejeitadas também não foram resgatadas, pelo mesmo motivo.

## 2. Canonização de proposições

### Por que

A auditoria anterior (`docs/proposition_polarity_audit.md`) examinou apenas desacordos, com um juiz que via as stances.

Além disso, ela comparava lados trocados na expansão:
- `expansion29_model_predictions.csv` está na ordem de apresentação do anotador 1, e em 16 dos 29 pares o lado A do modelo é o lado B do gold;
- por isso, 6 dos 13 "desacordos modelo × gold" daquela auditoria comparavam lados diferentes;
- as métricas de relação e comparabilidade publicadas antes não são afetadas, porque são simétricas.

### Desenho

- **Cobertura:** todos os lados em que as duas fontes dão stance determinada, incluindo acordos.
- **Julgamento:** dois juízes cegos às stances classificam cada par de proposições em EQUIVALENT / OPPOSITE_POLARITY / DIFFERENT / UNCERTAIN. A stance de Y só é invertida quando os dois juízes dizem OPPOSITE_POLARITY.
- **Alinhamento:** as previsões da expansão são realinhadas à ordem cronológica. Um teste confere o texto dos 29 pares.
- **Concordância entre juízes:** 85,8%, κ = 0,73. Nenhuma saída malformada.

### Resultados

| Fonte | n lados | κ stance antes | κ depois | desacordo→acordo | acordo→desacordo |
|---|---:|---:|---:|---:|---:|
| Humano × humano, piloto | 34 | 0,82 | 0,82 | 0 | 0 |
| Humano × humano, expansão | 55 | 0,27 | **0,54** | 5 | 0 |
| Modelo × gold, piloto | 66 | 0,56 | 0,65 | 4 | 1 |
| Modelo × gold, expansão | 107 | 0,39 | **0,06** | 1 | 4 |

- **Humanos:** 5 dos 8 desacordos de stance da expansão são só polaridade da formulação, e nenhum acordo esconde desacordo. A concordância real entre anotadores é moderada (κ 0,54), e não fraca como indicava o κ de 0,27.
- **Modelos na expansão:** o quadro piora depois do alinhamento. Aparecem 4 "acordos" que eram desacordos escondidos.
  - Exemplo, par `ffe531755c6def2e` (motoristas de aplicativo): o modelo escreve "o projeto deve ser **rejeitado**" e marca AGAINST, e o gold marca AGAINST para "a Câmara deve **aprovar** o projeto".
  - O modelo aplica o sinal ao tema, e não à própria frase que escreveu: uma dupla negação.
  - 4 dos 5 casos vêm desse único par, então o efeito agregado no κ é frágil. Em n = 107 com ~90% FAVOR, o κ oscila muito.
- **Dentro dos pares comparáveis do gold** (12 MAINTAINED): nenhum par tem proposições com polaridade oposta. Não há reversão escondida no gold por formulação. O mesmo vale para os pares que os modelos julgaram comparáveis.

## Limitações

- As amostras aceitas são pequenas (7, 7, 8 e 17 por operação). Os ICs de Wilson são largos, e os resultados devem ser lidos como direção e mecanismo, não como taxas.
- Reescritas sintéticas não são reversões naturais. Só o lado B foi alterado, e o texto pode ter pistas de edição que um humano notaria.
- O verificador é um único modelo e deixou passar erros de cópia (ver acima).
- A comparação com as previsões originais da expansão mistura ordens de apresentação: os originais foram rodados na ordem do anotador 1, e os contrafactuais na ordem cronológica. As relações são simétricas, mas a ordem pode influenciar o modelo.
- Os juízes da canonização são LLMs. O julgamento é `MODEL_JUDGMENT`, uma lente diagnóstica, e nunca substitui rótulos humanos.

## Artefatos e reprodução

```
src/voxlab/synthetic_stress.py              src/voxlab/proposition_canonicalization.py
prompts/stress_generate_v1.txt              prompts/proposition_canonicalization_v1.txt
prompts/stress_verify_v1.txt
data/processed/stress/                      data/processed/canonicalization/
  stress_plan.csv                             canonicalization_items.csv
  stress_generation_audit.csv                 canonicalization_summary.json
  stress_predictions.csv
  stress_metrics.json, stress_manifest.json
data/processed/llm_raw_outputs/stress/*.json   (857 respostas brutas)
```

```bash
PYTHONPATH=src python3 -m voxlab.synthetic_stress                        # dry-run: plano e custo
PYTHONPATH=src python3 -m voxlab.synthetic_stress --execute              # usa o cache; só chama o que falta
PYTHONPATH=src python3 -m voxlab.proposition_canonicalization --execute
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
