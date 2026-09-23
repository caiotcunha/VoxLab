# Análise final do consenso semântico

## Validação do arquivo

O arquivo `data/annotations/semantic_pilot_consensus.csv`, validado em 2026-09-23, contém os 18 pares esperados, com 18 `pair_id` distintos. Não há ID ausente, duplicado ou desconhecido. Todos os 18 registros têm respostas completas e válidas, e evento, data, assunto, turno, contexto e evidência coincidem com os pacotes cegos originalmente entregues.

A apresentação A/B foi randomizada independentemente para os anotadores. Em 11 dos 18 pares eles receberam ordens opostas. A validação restaura todas as respostas dependentes de lado para a ordem cronológica da fonte antes de comparar ou gerar o gold. `same_proposition` e `comparability_confidence` permanecem no nível do par.

Dezesseis registros recebidos contêm caracteres de controle recuperáveis de uma conversão Windows-1252 nos campos de exibição. O consenso original é preservado. O gold reconstrói os textos diretamente do `PublicHearingBR_LDS.jsonl`, usando os offsets documentais validados, e por isso não transporta esses caracteres corrompidos.

## Distribuição final

| Decisão | Resultado |
|---|---:|
| Determinabilidade por lado | 36 `YES` de 36 (100%) |
| Mesma proposição por par | 5 `YES` (27,8%); 11 `NO` (61,1%); 2 `UNCERTAIN` (11,1%) |
| Stance por lado | 28 `FAVOR` (77,8%); 8 `AGAINST` (22,2%) |
| Relação derivada | 5 `STANCE_MAINTAINED`; 11 `INCOMPARABLE`; 2 `RELATION_UNCERTAIN` |
| `STANCE_REVERSED` | 0 |
| `INSUFFICIENT_EVIDENCE` | 0 |

Os dois pares incertos são `263f772b51bf1354` (Alexandre da Silva) e `8f79764e69daadf2` (Alexandre Lindenmeyer). A relação consensual coincide com a de ambos os anotadores em 13 pares, somente com a do anotador 2 em 4 e com nenhum em 1. Essa comparação descreve o resultado; ela não identifica quem conduziu o consenso nem mede influência entre participantes.

## Gold do piloto

`data/annotations/semantic_pilot_gold.csv` é o gold humano adjudicado do piloto. Ele contém os 18 pares em ordem cronológica, os textos literais reconstruídos da fonte, as respostas consensuais, a relação determinística, `label_source=HUMAN_CONSENSUS` e o SHA-256 do consenso que originou cada linha. A referência identificada permanece separada; o gold não adiciona nome ou partido como campo estruturado.

O arquivo não deve ser tratado como benchmark final. Ele é pequeno, tem somente cinco exemplos positivos de comparabilidade, dois incertos e nenhuma reversão. Serve para confirmar o fluxo de anotação, estudar os erros do gate e orientar uma amostra maior.

## Decisão científica

- **GO limitado para a próxima etapa do comparability gate:** o piloto produziu exemplos humanos de pares comparáveis e incomparáveis, e a concordância independente anterior foi 81,25% (`kappa=0,6279`) para mesma proposição.
- **WARNING para avaliação quantitativa:** 18 pares não sustentam estimativas estáveis nem divisão robusta entre desenvolvimento e teste. Uma expansão estratificada do gold deve preservar exemplos difíceis e aumentar os pares comparáveis.
- **NO-GO para alegar detecção de reversão:** nenhuma instância `STANCE_REVERSED` foi observada. O piloto atual não permite medir recall dessa classe nem sustentar conclusões sobre sua frequência no corpus.

O próximo experimento deve separar o gate binário de comparabilidade da classificação de stance e manter `UNCERTAIN` fora das métricas binárias principais ou reportá-lo separadamente. O piloto deve permanecer congelado como evidência da fase de viabilidade.

## Artefatos e reprodução

- `data/annotations/semantic_consensus_comparison.csv`: consenso em ordem cronológica e comparação com os dois anotadores.
- `data/processed/semantic_consensus_analysis.json`: integridade, hash, distribuições e alinhamento.
- `data/annotations/semantic_pilot_gold.csv`: gold humano adjudicado do piloto.
- `src/voxlab/consensus.py`: valida schema, fonte, orientação, completude e gera o gold somente sem bloqueios.

```bash
PYTHONPATH=src python3 -m voxlab.consensus
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
