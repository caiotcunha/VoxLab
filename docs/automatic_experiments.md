# Baselines automáticos (LLM) para o comparability gate

**Trilha experimental separada.** Este documento descreve chamadas de API externas via DeepInfra, avaliadas contra o gold humano de 18 pares. Isso é fundamentalmente diferente do resto do pipeline (`audit.py`, `provenance.py`, `expansion.py`, `agreement.py`, `consensus.py`), que é 100% stdlib e nunca chama um modelo. Nenhum LLM é classificador em nenhuma outra parte deste projeto.

**Estado dos 29 pares da expansão:** não têm rótulo humano. Nada neste documento usa accuracy, F1 ou "correto" em relação a eles. Toda previsão sobre os 29 é `label_source=MODEL_PREDICTION` e é descrita como "previsão do modelo sobre o conjunto não rotulado", nunca como resultado avaliado.

**Princípio da rodada:** o objetivo era tentar refutar a hipótese do comparability gate, não confirmá-la. Os prompts foram congelados antes de qualquer resultado do gold ser observado; nenhum ajuste foi feito a partir de erro observado no gold (ver §4).

---

## 1. Experimental setup

- Implementação: `src/voxlab/llm_client.py` (cliente HTTP mínimo, stdlib-only) e `src/voxlab/automatic_baselines.py` (parsers, derivação, métricas, orquestração).
- Provedor: DeepInfra (`https://api.deepinfra.com/v1/openai/...`), API compatível com OpenAI.
- Chave: fornecida pelo usuário via chat, armazenada apenas em `VoxLab/.env` (gitignored). Nunca aparece em código, CSV, JSON ou log. Recomenda-se rotacionar a chave após esta rodada, já que passou pelo histórico de conversa.
- Temperatura: `0.0`. Seed: `20260924`, quando suportada pelo endpoint.
- `data/processed/automatic_experiment_manifest.json` registra a configuração congelada: hashes SHA-256 dos dois prompts, modelos, temperatura, seed, contagem de pares, versão da derivação de relação e commit do git no momento da congelamento.
- Custo real medido: ≈ US$ 0,40 para a rodada completa (18 gold + 29 expansão, 2 condições de chamada, 2 modelos) — medido a partir do campo `usage.estimated_cost` de chamadas reais, não estimado.
- Toda resposta bruta de cada chamada foi salva em `data/processed/llm_raw_outputs/{condição}_{modelo}_{pair_id}.json`, nunca editada manualmente. As respostas são lidas do cache em reexecuções (nenhuma chamada é refeita se o raw já existe em disco) — isso preservou o progresso através de três falhas transitórias de rede/servidor durante a coleta (ver §16).

## 2. Human gold

Os 18 pares de `data/annotations/semantic_pilot_gold.csv` são o único gold humano. Distribuição: 5 `STANCE_MAINTAINED`, 11 `INCOMPARABLE`, 2 `RELATION_UNCERTAIN`, 0 `STANCE_REVERSED`. Os modelos nunca recebem os campos de resposta humana como entrada — apenas `DISPLAY_FIELDS` de `semantic_pilot.py` (evento, data, tema, fala literal cega dos dois lados). `load_blind_pairs_from_gold` é testado para nunca expor `same_proposition`, `stance_a` ou `derived_relation`.

## 3. Models

Dois modelos hospedados na DeepInfra, confirmados contra o endpoint `/v1/openai/models` antes de qualquer chamada de inferência (não assumidos por nome):

- `Qwen/Qwen2.5-72B-Instruct` — contexto 32.768 tokens, preço US$0,36/US$0,40 por milhão de tokens (entrada/saída).
- `meta-llama/Llama-3.3-70B-Instruct-Turbo` — contexto 131.072 tokens, preço US$0,10/US$0,32 por milhão de tokens (entrada/saída).

Ambos processados de forma independente; concordância entre eles nos 29 pares é `INTER_MODEL_AGREEMENT` (§14), nunca gold.

## 4. Prompt freezing

Sequência seguida: desenvolver prompts → validar apenas estrutura/schema em exemplos sintéticos (testes sem rede) → versionar como arquivo (`prompts/baseline_a_end_to_end_v1.txt`, `prompts/structured_extraction_v1.txt`) → calcular SHA-256 → registrar no manifesto → congelar → rodar os 18 gold → calcular métricas → **não tocar nos prompts depois disso**.

Durante a coleta houve três falhas técnicas reais (timeout de rede, erro 500 e erro 429 "engine_overloaded" da DeepInfra) — todas transitórias, confirmadas ao reexecutar a mesma chamada minutos depois com sucesso. Nenhuma delas motivou mudança de prompt; foram tratadas como falha de infraestrutura (retry com backoff em `llm_client.py`), não como `prompt_v2`. Uma correção de parser foi feita depois de ver os primeiros resultados (§16) — não alterou nenhuma previsão de relação, apenas a contabilização de erro de schema, e é documentada como exceção justificada, não como ajuste de prompt.

## 5. Baseline A — end-to-end

Uma chamada por par×modelo. O modelo recebe as duas manifestações cegas e devolve a relação final diretamente, sem etapas intermediárias — nenhuma extração de proposição, nenhum julgamento de comparabilidade explícito. Prompt: `prompts/baseline_a_end_to_end_v1.txt`.

## 6. Pipeline B — structured, sem gate

Não é uma chamada de LLM separada. Deriva-se da mesma extração estruturada do item 7, mas ignorando `same_proposition` (equivalente a assumir sempre `YES`). Isola o efeito do gate: B e C compartilham exatamente a mesma extração; a única diferença é usar ou não `same_proposition` na derivação.

## 7. Pipeline C — structured, com gate

Uma chamada por par×modelo, pedindo `stance_determinable_a/b`, `target_proposition_a/b`, `same_proposition`, `stance_a/b`. Prompt: `prompts/structured_extraction_v1.txt`, reaproveitando literalmente as definições de `docs/annotation_guideline.md`. A relação final é derivada por `agreement.derive_relation(...)` sem modificação — a mesma função usada para as anotações humanas do piloto.

## 8. Metrics — definições fixadas antes da execução

- **False reversal:** par classificado como `STANCE_REVERSED` quando `relation_gold != STANCE_REVERSED`. Denominador fixo: 18 (todos os pares do gold), independentemente de quantos positivos reais existem.
- **Recall/F1 de `STANCE_REVERSED`:** reportado como `undefined_not_estimable_zero_positives_in_gold` — o gold não tem nenhuma instância dessa classe.
- **Comparability accuracy/F1:** binário YES/NO sobre `same_proposition`; pares gold `UNCERTAIN` são excluídos e contados separadamente (`n_gold_uncertain_excluded`), não tratados como um terceiro valor binário nem descartados silenciosamente.
- **Malformed output ≠ incerteza semântica:** um valor fora do vocabulário do schema é `malformed_output=true` com `malformed_fields` explícito, nunca dobrado silenciosamente em um `UNCERTAIN` legítimo. `valid_output_rate`/`schema_failure_rate` são reportados por modelo × condição.
- **Macro-F1** é reportado mas não é o número de destaque — a leitura central usa a tabela de efeito do gate, comparabilidade binária, falsas reversões e a matriz de confusão.

## 9. Gold-18 results

| Métrica | Qwen2.5-72B | Llama-3.3-70B |
|---|---:|---:|
| Accuracy — end-to-end (A) | 0,7778 | **0,8333** |
| Accuracy — structured sem gate (B) | 0,2222 | 0,2778 |
| Accuracy — structured com gate (C) | 0,7778 | 0,7222 |
| Macro-F1 (A / B / C) | 0,807 / 0,400 / 0,876 | 0,871 / 0,500 / 0,792 |
| Comparability accuracy (binário YES/NO, n=16) | 0,9375 | 0,875 |
| Comparability F1 (classe YES) | 0,889 | 0,750 |
| Comparability precision/recall (YES) | 1,000 / 0,800 | 1,000 / 0,600 |
| Valid output rate (end-to-end / structured) | 1,0 / 1,0 | 1,0 / 1,0 |
| False reversal count (A / B / C) | 0 / 0 / 0 | 0 / 1 / 0 |
| False reversal rate (A / B / C), denom=18 | 0 / 0 / 0 | 0 / 0,0556 / 0 |

Nos dois modelos, **B (sem gate) é dramaticamente pior que C (com gate)** — accuracy cai de ~0,78/0,72 para ~0,22/0,28. Isso por si só não isola o efeito do gate de forma limpa (ver §10-11 para a comparação correta B vs C, que já está isolada por construção). O achado que exige mais cuidado: **A (end-to-end) empata com C no Qwen e supera C no Llama** — o pipeline estruturado com gate não superou o baseline direto de ponta a ponta nesta amostra.

## 10. Gate ablation (B → C)

B e C usam a mesma extração estruturada; a única variável é o uso de `same_proposition`.

| Modelo | ERROR→CORRECT | CORRECT→ERROR | CORRECT→CORRECT | ERROR→ERROR |
|---|---:|---:|---:|---:|
| Qwen2.5-72B | 10 | 0 | 4 | 4 |
| Llama-3.3-70B | 10 | 2 | 3 | 3 |

O gate corrige 10 dos 18 pares nos dois modelos. No Qwen, nunca piora um caso que já estava certo (0 CORRECT→ERROR). No Llama, o gate estraga 2 casos que sem ele estavam certos.

## 11. Pairwise gate effect — detalhamento

**ERROR→CORRECT (idêntico nos dois modelos, 10 pares):** `0138e27cd0f53d95`, `2a22c99d1d3a678c`, `2e42e8583aea6939`, `36e4b11ff6345a11`, `36fb1e1240a12ac4`, `4cffd4e8a3906c01`, `af4d70f0c140e9c9`, `d4e87de87b4f3431`, `de54c782d361768c`, `ebcdef50abd4418f`. Todos são gold `INCOMPARABLE`; sem o gate, os dois modelos previam uma relação de stance (`STANCE_MAINTAINED` na maioria, uma vez `STANCE_REVERSED` no Llama) porque a comparação ignorava se as proposições eram a mesma.

**CORRECT→ERROR (só no Llama, 2 pares):** `3459768d16f576e5` e `e001ebac1d8033f1` — ambos gold `STANCE_MAINTAINED`. O Llama previu `same_proposition=NO` nesses dois casos (falso negativo de comparabilidade), fazendo o gate transformar um acerto de stance em `INCOMPARABLE` incorretamente.

## 12. Error analysis — foco em INCOMPARABLE

Dos 11 pares gold `INCOMPARABLE`: **sem gate, 0/11 foram classificados corretamente nos dois modelos** — o gate é responsável por praticamente 100% da capacidade de detectar incomparabilidade nesta amostra. **Com gate, 10/11 corretos nos dois modelos.** O único caso que permanece errado nos dois (`e6a308550846aa5f`) tem `same_proposition=NO` corretamente predito, mas é classificado como `INSUFFICIENT_EVIDENCE` em vez de `INCOMPARABLE` — porque `stance_determinable` foi `NO` em um dos lados, e essa condição tem precedência na derivação (`agreement.derive_relation`). Não é uma falha do gate; é um caso onde a evidência de stance também foi julgada insuficiente.

Contagem de acertos totais (18 pares): end-to-end (A) = 14 (Qwen) / 15 (Llama); estruturado com gate (C) = 14 (Qwen) / 13 (Llama).

## 13. False reversals

Zero em toda condição×modelo, exceto **1 caso**: Llama, condição B (sem gate), no par gold `INCOMPARABLE` `4cffd4e8a3906c01`, onde a comparação direta de stances produziu `STANCE_REVERSED`. Com o gate (condição C), esse mesmo par é corretamente classificado como `INCOMPARABLE`. Esse é o único caso, nos dois modelos e nas três condições, onde o gate elimina uma falsa reversão observada — mas a amostra é pequena demais para generalizar essa taxa.

## 14. Inter-model comparison

Concordância entre Qwen e Llama nos **29 pares não rotulados da expansão** — rotulado explicitamente `INTER_MODEL_AGREEMENT`, nunca gold, nunca validação, nunca usado para promover qualquer par:

| Campo | Raw agreement | Cohen's kappa |
|---|---:|---:|
| `same_proposition` | 0,7931 | 0,514 |
| `stance_a` | 0,9310 | 0,749 |
| `relation` (com gate) | 0,7241 | 0,468 |

Concordância moderada a substancial, mas não alta — os dois modelos discordam em cerca de 1 a cada 4 pares na relação final com gate. Isso não diz nada sobre qual modelo está certo: nenhum dos dois tem gold nos 29 pares.

## 15. Predictions on unlabeled expansion-29

Nenhuma métrica de acerto é calculada aqui — não há gold. `data/processed/expansion29_model_predictions.csv` tem 58 linhas (29 pares × 2 modelos), todas com `label_source=MODEL_PREDICTION`, 0 saídas malformadas.

Distribuição de relação prevista (condição com gate):

| Relação | Qwen2.5-72B | Llama-3.3-70B |
|---|---:|---:|
| `INCOMPARABLE` | 16 | 22 |
| `STANCE_MAINTAINED` | 9 | 5 |
| `INSUFFICIENT_EVIDENCE` | 4 | 2 |
| `STANCE_REVERSED` | 0 | 0 |

**Nenhum dos dois modelos classificou qualquer par dos 29 como `STANCE_REVERSED`** na condição com gate. Isso é uma observação sobre o comportamento do modelo no conjunto não rotulado, não uma afirmação sobre a taxa real de reversão no corpus — os 29 pares não têm verdade de referência humana.

## 16. Limitations

- **18 pares gold** é uma amostra minúscula para estimar performance com confiança — cada erro/acerto individual move a accuracy em ~5,5 pontos percentuais.
- **Zero `STANCE_REVERSED` no gold** impede qualquer estimativa de recall dessa classe, que é justamente a classe de interesse científico original do projeto.
- **Bug de parser corrigido depois de ver o gold** (não um ajuste de prompt): a implementação inicial tratava incorretamente `stance_a`/`stance_b` vazio como erro de schema quando, na verdade, o próprio prompt instrui o modelo a deixar esses campos vazios quando `stance_determinable` não é `YES`. Isso inflava artificialmente `malformed_output_count` (3 casos no Qwen, 2 no Llama) sem afetar nenhuma relação predita — confirmado reprocessando os mesmos raw outputs já salvos, sem nenhuma chamada nova de API. Depois da correção, `valid_output_rate=1.0` para as duas condições nos dois modelos. Isso é registrado aqui com total transparência porque é exatamente o tipo de ajuste pós-hoc que o desenho experimental pretendia evitar; a diferença crítica é que corrigiu uma contagem de qualidade de output, não uma previsão de relação avaliada.
- **Falhas transitórias de rede/servidor** (timeout, 500, 429) durante a coleta, todas resolvidas por retry — não indicam problema sistemático de disponibilidade do provedor, mas mostram que a coleta não foi um processo limpo de ponta a ponta.
- **Um único par (`597ab529d9e58c55`) teve uma fala de ~19.000 caracteres** e sofreu repetidas falhas transitórias antes de suceder — pode indicar que prompts muito longos são mais sensíveis a sobrecarga momentânea do provedor.

## 17. Threats to validity

- **Vazamento de conhecimento agregado:** esta sessão já conhecia a distribuição agregada do gold (5/11/2/0) antes de rodar os baselines, por ter acompanhado o projeto desde a criação do piloto. Os prompts foram escritos antes dessa rodada e não foram ajustados por par individual, mas o conhecimento da distribuição de classes é uma forma leve de exposição que não pode ser completamente descartada.
- **Confiabilidade do gold em si:** o próprio gold humano tem apenas 18 pares e concordância inter-anotador imperfeita documentada em `docs/semantic_agreement.md` — parte do "erro" atribuído ao modelo pode refletir ambiguidade real do caso, não falha do modelo.
- **Um único gold, sem holdout:** os 18 pares serviram tanto para desenhar o protocolo quanto para avaliar os baselines — não há um conjunto de teste verdadeiramente não visto por ninguém durante o desenho metodológico do projeto.
- **Dois modelos, uma família de arquitetura similar:** Qwen2.5 e Llama-3.3 são ambos LLMs generalistas de peso aberto na faixa de 70B parâmetros; concordância ou discordância entre eles não generaliza para arquiteturas muito diferentes (ex.: modelos pequenos, modelos fechados, modelos especializados).

## 18. É necessária a anotação humana dos 29?

Sim — nenhuma evidência aqui substitui isso. Os modelos concordam moderadamente entre si (κ 0,47–0,75) mas isso é `INTER_MODEL_AGREEMENT`, não confirmação de correção. O comparability accuracy no próprio gold (0,875–0,9375) ainda deixa 1-2 erros em 16 casos binários — inclusive com `recall_YES` de apenas 0,6–0,8, ou seja, os modelos deixam passar 20-40% dos pares genuinamente comparáveis como incomparáveis. Isso é suficiente para não confiar nas previsões automáticas dos 29 como substituto do gold. Ver decisão H abaixo.

---

## Decisão final

**A) O pipeline estruturado supera o baseline end-to-end?** Não. Empatou no Qwen (14/18 vs 14/18) e perdeu no Llama (13/18 vs 15/18). Nesta amostra pequena, decompor em etapas não trouxe vantagem sobre pedir a relação direto.

**B) Isolando B vs C, o comparability gate melhora os resultados?** Sim, de forma inequívoca. Accuracy sobe de 0,22–0,28 para 0,72–0,78 nos dois modelos quando o gate é usado, isolando exatamente essa variável.

**C) Quantos erros o gate corrigiu?** 10 em cada modelo, todos pares gold `INCOMPARABLE` que a comparação direta de stance classificava incorretamente como relação de stance.

**D) Quantos acertos o gate estragou?** 0 no Qwen. 2 no Llama — ambos pares gold `STANCE_MAINTAINED` onde o modelo previu `same_proposition=NO` incorretamente.

**E) Quantos falsos `STANCE_REVERSED` cada condição produziu?** 0 em quase todas as condições. A única exceção: Llama, condição sem gate, 1 falso `STANCE_REVERSED` — eliminado quando o gate é aplicado.

**F) O efeito aparece nos dois modelos ou depende do modelo?** O ganho do gate (B→C) aparece nos dois modelos de forma muito similar em magnitude (accuracy +0,50 a +0,56). O único ponto que difere é que o gate nunca piora nada no Qwen mas piora 2 casos no Llama — dependência de modelo real, mas de segunda ordem frente ao efeito principal.

**G) 18 exemplos sustentam uma conclusão forte?** Não sobre a taxa exata de qualquer métrica — cada par vale ~5,5 pontos de accuracy. Mas o padrão qualitativo (gate corrige 10/11 INCOMPARABLE; sem gate falha em 11/11) é grande e consistente o suficiente entre dois modelos independentes para não ser atribuído a ruído de amostra pequena.

**H) A anotação humana dos 29 ainda é metodologicamente necessária?** **Sim.** O comparability accuracy no próprio gold humano ainda tem recall de 0,6–0,8 para a classe `YES` — os modelos perdem entre 20% e 40% dos pares genuinamente comparáveis mesmo no melhor caso observado. Concordância entre modelos nos 29 (κ 0,47–0,75) mostra que eles nem sempre concordam entre si, e concordância não é validação. Nenhuma previsão automática deste documento deve ser tratada como rótulo para treinar, avaliar ou reportar como resultado do estudo de reversão de postura — apenas como evidência exploratória de que o gate, isolado, tem efeito real e mensurável.

---

## Artefatos

```
data/processed/automatic_experiment_manifest.json
data/processed/gold18_end_to_end_predictions.csv
data/processed/gold18_structured_predictions.csv
data/processed/gold18_gate_ablation.csv
data/processed/gold18_pairwise_analysis.csv
data/processed/gold18_metrics.json
data/processed/expansion29_model_predictions.csv
data/processed/expansion29_intermodel_agreement.json
data/processed/llm_raw_outputs/*.json   (188 respostas brutas, 1 por chamada)
prompts/baseline_a_end_to_end_v1.txt
prompts/structured_extraction_v1.txt
src/voxlab/llm_client.py
src/voxlab/automatic_baselines.py
tests/test_llm_client.py
tests/test_automatic_baselines.py
```

## Reprodução

```bash
cd VoxLab
# .env com DEEPINFRA_API_KEY, nunca versionado
PYTHONPATH=src python3 -m unittest discover -s tests -v   # 124 testes, sem rede
PYTHONPATH=src python3 -m voxlab.automatic_baselines        # usa cache de llm_raw_outputs/ quando existente
```
