# Diagnóstico: viés de polaridade na formulação da proposição

**Origem:** um anotador humano notou, ao montar a planilha de consenso da expansão, que `target_proposition` é texto livre — a mesma posição real pode ser formulada de forma afirmativa ou negada, invertendo FAVOR/AGAINST sem nenhuma discordância substantiva real sobre o que o ator disse.

**O que este documento NÃO é:** não é uma correção de gold, consenso ou predição. Nenhum arquivo existente foi reescrito. É uma camada diagnóstica sobre desacordos de stance já observados, usando um único julgamento de LLM (Qwen2.5-72B-Instruct, `prompts/proposition_polarity_audit_v1.txt`) como lente exploratória — esse julgamento tem seu próprio erro e não é tratado como verdade.

> **Correção (2026-09-28).** A linha `model_vs_gold_expansion` abaixo compara lados trocados em parte dos casos. `expansion29_model_predictions.csv` está na ordem de apresentação do anotador 1, e em 16 dos 29 pares o lado A do modelo corresponde ao lado B do gold. Seis dos 13 casos dessa fonte comparam manifestações diferentes. Portanto, a conclusão de que o viés de polaridade "não explica" a queda do modelo na expansão não se sustenta como estava escrita.
>
> A análise refeita com os lados realinhados, cobrindo também os acordos e usando dois juízes cegos às stances, está em `docs/stress_and_canonicalization.md` (§2). Lá, na expansão, a canonização encontra mais desacordos escondidos do que artefatos, sobretudo em um único par. As linhas `human_human_expansion` e `model_vs_gold_pilot` não tinham o problema de alinhamento. Os arquivos gerados por este módulo foram preservados como estavam.

## Método

Para cada caso onde já existia desacordo de stance (FAVOR vs AGAINST) entre duas fontes sobre o mesmo lado do mesmo par, perguntou-se: as duas formulações de proposição descrevem a mesma reivindicação substantiva, só que com polaridade oposta? Três fontes de desacordo, todas já existentes antes deste diagnóstico:

- **`human_human_expansion`**: os dois anotadores humanos discordaram de stance em algum lado, nos 29 pares da expansão (`expansion_semantic_annotation_comparison.csv`).
- **`model_vs_gold_pilot`**: a extração estruturada de um modelo (Qwen ou Llama) discordou do gold humano de 18 pares.
- **`model_vs_gold_expansion`**: idem, contra o gold humano recém-gerado de 29 pares.

30 casos no total — todos os desacordos existentes, nenhuma amostragem.

## Resultado

| Fonte | Casos | Artefato de polaridade (YES) | Desacordo real (NO) | Incerto |
|---|---:|---:|---:|---:|
| Humano × humano (expansão) | 8 | **5 (62,5%)** | 3 | 0 |
| Modelo × gold (piloto, 18) | 9 | **5 (55,6%)** | 4 | 0 |
| Modelo × gold (expansão, 29) | 13 | 1 (7,7%) | 11 | 1 |

`malformed_output_count: 0` — nenhuma saída fora do vocabulário `YES/NO/UNCERTAIN`.

## Leitura

**A hipótese do anotador se confirma fortemente para o piloto e para a concordância humana:** mais da metade dos desacordos de stance entre os dois anotadores humanos, e mais da metade dos "erros" do modelo contra o gold do piloto, são explicados por polaridade de formulação, não por julgamento substantivo divergente. Exemplo típico (par `3459768d16f576e5`, piloto): um lado escreve "O saque-aniversário do FGTS deve ser mantido" (FAVOR), outro escreve "O governo deve acabar com o saque-aniversário do FGTS" (AGAINST) — a mesma posição real, formulada de forma oposta.

**Isso significa que o Kappa de stance reportado anteriormente (0,27 nos 29 pares; ver `docs/current_state.md`) provavelmente subestima a concordância humana real** — boa parte do que aparece como desacordo categórico é artefato de como cada anotador formulou a proposição, não divergência de leitura da fala.

**Mas isso NÃO explica a queda de desempenho do modelo no holdout prospectivo dos 29 pares:** lá, só 1 em 13 desacordos é artefato de polaridade; os outros 11 são divergência real. Ou seja, a queda de recall de comparabilidade e o efeito mais fraco/misto do gate observados em `expansion29_prospective_metrics.json` **não são explicados por este viés** — são, ao que tudo indica, uma queda real de desempenho do modelo em dados que ele nunca viu.

## Limitações

- O próprio julgamento de polaridade vem de um LLM (Qwen), não de um humano — é uma lente diagnóstica, não uma segunda verificação independente confiável.
- Um único modelo, sem checagem de concordância entre modelos para este julgamento específico.
- Amostra pequena (30 casos, 8 deles de uma única fonte) — as proporções por fonte têm intervalo de confiança largo.

## Decisão pendente (Fase 3, não implementada)

Se a equipe decidir que vale a pena, a sugestão original do anotador — um LLM propõe a formulação candidata da proposição e o humano valida/ajusta, em vez de escrever do zero — poderia reduzir esse artefato em rodadas **futuras** de anotação. Isso não deve ser aplicado retroativamente aos 18+29 pares já adjudicados por humano; a mudança de protocolo, se ocorrer, vale só para dados novos.

## Artefatos

```
data/processed/proposition_polarity_audit.csv
data/processed/proposition_polarity_audit_summary.json
prompts/proposition_polarity_audit_v1.txt
src/voxlab/proposition_polarity_audit.py
tests/test_proposition_polarity_audit.py
```

## Reprodução

```bash
cd VoxLab
PYTHONPATH=src python3 -m unittest discover -s tests -v   # 145 testes, sem rede
PYTHONPATH=src python3 -m voxlab.proposition_polarity_audit
```
