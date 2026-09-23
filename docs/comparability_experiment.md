# Protocolo exploratório do comparability gate

## Papel do piloto

Os 18 pares de `semantic_pilot_gold.csv` formam um conjunto de **desenvolvimento e viabilidade**. Eles participaram da construção da taxonomia e da guideline, portanto não constituem teste cego. Nenhum resultado nesta página é estimativa final de generalização.

O manifesto `data/processed/semantic_pilot_gold_manifest.json` congela o hash, o schema, os 18 IDs e o hash do consenso de origem. Uma futura avaliação deve usar pares novos, provenientes da expansão e sem participação na escolha de features ou limiares.

## Tarefa e política de rótulos

A unidade é um par de manifestações do mesmo ator em eventos distintos e cronologicamente ordenados. A tarefa primária do gate é binária:

| Consenso humano | Classe de avaliação |
|---|---|
| `same_proposition=YES` | `COMPARABLE` |
| `same_proposition=NO` | `INCOMPARABLE` |
| `same_proposition=UNCERTAIN` | excluído da métrica binária principal e reportado separadamente |

No piloto, isso produz 5 positivos, 11 negativos e 2 incertos. A classe positiva é `COMPARABLE`. As métricas previstas são macro-F1, balanced accuracy, precisão, recall e F1 da classe positiva, além da matriz de confusão. Sistemas capazes de abstenção também devem reportar cobertura.

## Entradas permitidas e prevenção de vazamento

Os baselines automáticos usam somente `topic_a/b`, `evidence_a/b` e `text_a/b`. Não entram como features:

- proposições-alvo escritas durante a anotação;
- notas e confianças humanas;
- stance humana, gold ou silver;
- relação adjudicada;
- nome, partido ou identidade estruturada do ator.

As proposições e notas aparecem em `comparability_pilot_diagnostics.csv` apenas para análise qualitativa posterior à predição.

## Baselines implementados

1. `always_incomparable`: baseline majoritário.
2. `always_comparable_no_gate`: representa um pipeline que deixa todos os pares seguirem para comparação de stance.
3. TF-IDF de assunto no limiar 0,10: reutiliza o corte de **recuperação de candidatos** como controle negativo. Ele não foi proposto como limiar de comparabilidade.
4. Rankings sem ajuste de limiar: TF-IDF de assunto, TF-IDF das evidências, TF-IDF dos turnos completos e Jaccard lexical das evidências.
5. Ablação com stance oráculo sem gate: usa a stance humana para isolar o efeito lógico de ignorar comparabilidade. Não é um modelo automático.

Nenhum limiar foi otimizado nos 18 pares. Para os rankings, reporta-se somente ROC AUC exploratória. Um limiar futuro deve ser escolhido no desenvolvimento e congelado antes do teste.

## Resultados exploratórios

Os dois casos `UNCERTAIN` ficam fora das métricas binárias, deixando 16 pares.

| Baseline fixo | Acurácia | Balanced accuracy | Macro-F1 | Recall `COMPARABLE` |
|---|---:|---:|---:|---:|
| Sempre `INCOMPARABLE` | 0,6875 | 0,5000 | 0,4074 | 0,0000 |
| Sempre `COMPARABLE` | 0,3125 | 0,5000 | 0,2381 | 1,0000 |
| TF-IDF de assunto ≥0,10 | 0,3125 | 0,5000 | 0,2381 | 1,0000 |

Todos os pares do piloto já haviam passado pelo corte de recuperação 0,10. Por isso, reutilizá-lo como gate equivale a prever todos como comparáveis e gera 11 falsos positivos. Isso confirma empiricamente que **candidate retrieval e comparability gate precisam ser componentes separados**.

| Ranking, sem escolher limiar | ROC AUC exploratória |
|---|---:|
| TF-IDF dos assuntos | 0,9091 |
| TF-IDF dos turnos completos | 0,8364 |
| TF-IDF das evidências | 0,6364 |
| Jaccard das evidências | 0,6364 |

Esses valores têm variância alta e viés de seleção: são apenas 5 positivos e 11 negativos, todos vindos de um piloto recuperado por similaridade de assunto. Eles servem para priorizar hipóteses, sem sustentar comparação final de modelos.

## Ablação sem gate

Comparar diretamente as stances humanas nos 18 pares emitiria 18 relações. Treze seriam indevidas porque o gold marcou a proposição como diferente ou incerta. Duas seriam chamadas de `STANCE_REVERSED`, mas ambas pertencem a pares `INCOMPARABLE`; o gold contém zero reversões verdadeiras.

Essa ablação mostra o mecanismo de erro previsto pela hipótese do projeto. Ela ainda não mede quanto um gate automático reduz o erro, pois usa comparabilidade e stance humanas e não há reversões positivas para medir recall.

## Análise qualitativa dos casos

Os exemplos revelam quatro fronteiras principais:

1. **Mesmo objetivo geral, instrumentos diferentes:** aprovar uma convenção versus executar um estatuto; ampliar orçamento versus escolher um estado piloto; reduzir fila versus atualizar protocolo.
2. **Mesmo tema amplo, objetos ou populações diferentes:** crianças e adolescentes versus regulação de redes; mulheres indígenas versus população LGBTQIA+; independência econômica versus saúde na menopausa.
3. **Avaliações positivas ou negativas sobre ações distintas:** coordenação do SUS versus participação social; contratação de empresa versus controle de diárias.
4. **Diferença de escopo e especificidade:** os dois `UNCERTAIN` contrapõem política nacional ou regional a prioridade municipal. Casos comparáveis também variam em idade, abrangência ou etapa da política, mostrando que sobreposição lexical isolada não resolve essa fronteira.

Nos pares `2a22c99d1d3a678c` e `36fb1e1240a12ac4`, ignorar o gate produziria as duas falsas reversões. O primeiro também evidencia que a formulação afirmativa ou negativa da proposição-alvo pode inverter o código de stance sem indicar mudança política.

## Próxima avaliação

1. Concluir a revisão documental dos 34 candidatos de expansão.
2. Anotar apenas os pares documentalmente validados, com duas pessoas e consenso.
3. Reservar os novos pares como teste ou definir a separação antes de observar seus rótulos.
4. Escolher limiares somente no conjunto de desenvolvimento.
5. Comparar gate versus pipeline sem gate, reportando falsos positivos de comparabilidade e falsas reversões.

## Reprodução

```bash
PYTHONPATH=src python3 -m voxlab.comparability_baselines
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Saídas:

- `data/processed/comparability_pilot_baselines.json`;
- `data/processed/comparability_pilot_diagnostics.csv`;
- `data/processed/semantic_pilot_gold_manifest.json`.
