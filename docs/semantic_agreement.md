# Concordância do piloto semântico humano

## Entradas e integridade

Foram recebidas 18 respostas completas de cada anotador para os mesmos 18 `pair_id`. O arquivo do anotador 1 está em UTF-8/CSV com vírgulas. O do anotador 2 foi exportado em Windows-1252 com ponto e vírgula e datas `DD/MM/AAAA`. O script lê ambos **sem regravar os originais**. Antes do cálculo, reconstrói os 18 pacotes cegos das fontes e confere cada texto, evidência, assunto, evento, data e mapeamento A/B. As únicas diferenças de apresentação observadas foram quebras de linha CRLF no arquivo 1 e formato de data no arquivo 2; não houve mudança substantiva do texto de origem.

As decisões foram trazidas de volta à ordem cronológica usando `semantic_pilot_reference.csv`. Uma nota livre que diga “A” ou “B” pode se referir à posição **visual** vista pelo anotador; `semantic_annotation_comparison.csv` preserva o mapeamento visual para interpretá-la. As proposições e stances com sufixo `_1_a`, `_2_b` etc. já estão na ordem cronológica.

## Métricas observadas

| Tarefa | Observações comparáveis | Concordância bruta | Kappa de Cohen | Atenção |
|---|---:|---:|---:|---|
| Stance determinável | 36 lados | 34/36 = 94,44% | 0,0000 | Anotador 2 marcou `YES` nos 36 lados; forte efeito de prevalência |
| Mesma proposição | 16 pares com dois lados determináveis para ambos | 13/16 = 81,25% | 0,6279 | Uma resposta `UNCERTAIN` no anotador 2 |
| Stance por lado | 34 lados determináveis para ambos | 32/34 = 94,12% | 0,8201 | Cada stance refere-se à proposição escrita por seu anotador |
| Relação derivada | 18 pares | 13/18 = 72,22% | 0,5028 | Uma classe rara (`RELATION_UNCERTAIN`) |

O Kappa zero da primeira linha não contradiz os 94,44% de concordância bruta: com o segundo anotador usando apenas `YES`, a concordância esperada pelas marginais coincide com a observada. Kappa e percentuais devem ser lidos junto das distribuições e dos casos individuais. As contagens detalhadas estão em `data/processed/semantic_agreement.json`.

O anotador 1 considerou ambos os lados determináveis em 16/18 pares; o anotador 2, em 18/18. O anotador 1 marcou `same_proposition=YES` em 7/16 pares aplicáveis; o anotador 2, em 5/18. Entre os 16 pares em que a decisão era aplicável para ambos, o anotador 2 marcou `YES` em 4, `NO` em 11 e `UNCERTAIN` em 1. As relações derivadas foram: anotador 1, 9 `INCOMPARABLE`, 2 `INSUFFICIENT_EVIDENCE` e 7 `STANCE_MAINTAINED`; anotador 2, 12 `INCOMPARABLE`, 1 `RELATION_UNCERTAIN` e 5 `STANCE_MAINTAINED`. **Nenhum anotador produziu `STANCE_REVERSED` no piloto.** Isso é um resultado da amostra, não prova ausência de reversões no corpus.

Na comparação direta dos 16 pares aplicáveis para ambos, **4** receberam `same_proposition=YES` dos dois anotadores, **9** receberam `NO` dos dois e **3** divergiram. Nas relações derivadas dos 18 pares, ambos concordaram em 4 `STANCE_MAINTAINED` e 9 `INCOMPARABLE`; os outros 5 são os conflitos abaixo. Mesmo os quatro pares concordantes como `STANCE_MAINTAINED` ainda precisam de revisão das proposições-alvo antes de entrar no gold.

## Casos para discutir

Cinco pares têm relação derivada diferente:

| Par | Ator | Foco da divergência |
|---|---|---|
| `263f772b51bf1354` | Alexandre da Silva | Mesma proposição: `YES` vs `UNCERTAIN` |
| `24c599750bdd544f` | Any Ortiz | Determinabilidade da segunda manifestação: `NO` vs `YES` |
| `8f79764e69daadf2` | Alexandre Lindenmeyer | Mesma proposição: `YES` vs `NO` |
| `0138e27cd0f53d95` | Aliel Machado | Mesma proposição: `YES` vs `NO` |
| `e6a308550846aa5f` | Leônidas Cristino | Determinabilidade da primeira manifestação: `NO` vs `YES` |

Há ainda duas divergências de stance que **não** mudam a relação derivada porque ambos os anotadores classificaram os pares como incomparáveis: `2a22c99d1d3a678c` (Dr. Zacharias Calil, lado A) e `36fb1e1240a12ac4` (Célia Xakriabá, lado B). No primeiro, um anotador escreveu a proposição em forma afirmativa e o outro em forma aproximadamente negada; `FAVOR` versus `AGAINST` pode refletir essa orientação da frase. No segundo, os alvos escritos parecem abordar objetos diferentes. Essas stances não devem ser comparadas como se respondessem automaticamente ao mesmo alvo.

Nenhuma das **36 comparações por lado** de proposição-alvo coincide literalmente entre anotadores; em dois lados, um deles deixou a proposição vazia por ter marcado determinabilidade `NO`. Igualdade textual não foi usada como requisito; equivalência semântica precisa de revisão humana. Por isso, a fila de adjudicação contém **todos os 18 pares**, com os cinco conflitos de relação e os dois conflitos adicionais de stance sinalizados. `semantic_annotation_comparison.csv` preserva todas as decisões e notas em ordem cronológica; `semantic_adjudication_queue.csv` acrescenta somente campos vazios para adjudicação.

## Como adjudicar e formar gold

Uma pessoa diferente dos dois anotadores, quando disponível, deve abrir `data/annotations/semantic_adjudication_queue.csv` junto com `semantic_pilot_reference.csv` e as transcrições de origem. Não altere os CSVs dos anotadores. A fila contém ator e evidências para inspeção; essa fase é deliberadamente não cega.

Para **cada par**:

1. Confira se as proposições escritas pelos dois anotadores para cada lado são semanticamente equivalentes e sustentadas pela fala. Preencha `proposition_equivalent_after_review_a/b` com `YES`, `NO`, `UNCERTAIN` ou `NOT_APPLICABLE` quando faltar proposição em um lado.
2. Resolva determinabilidade, uma proposição-alvo específica por manifestação, comparabilidade e stance em `adjudicated_stance_determinable_a/b`, `adjudicated_target_proposition_a/b`, `adjudicated_same_proposition` e `adjudicated_stance_a/b`. Mantenha a ordem cronológica A/B da fila. Use `NO` para falta de stance, não para neutralidade.
3. Registre a justificativa em `adjudicator_notes` e marque `adjudication_status` como `RESOLVED`, `PENDING` ou `EXCLUDED`. Questões sem suporte documental devem permanecer pendentes ou excluídas.

**Atualização de 2026-09-23:** a adjudicação foi recebida em `semantic_pilot_consensus.csv`, validada e convertida em `semantic_pilot_gold.csv`. Os resultados finais e a decisão científica estão em `docs/semantic_consensus_analysis.md`. Esta seção preserva o procedimento definido antes do consenso.

## Reprodução

Da raiz do repositório, sem modificar as anotações originais:

```bash
PYTHONPATH=src python3 -m voxlab.agreement
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

O script lê ambos os formatos de CSV, valida as planilhas contra a fonte e grava `data/processed/semantic_agreement.json`, `data/annotations/semantic_annotation_comparison.csv` e a fila de adjudicação. Se a fila já contiver decisões humanas, o script não as sobrescreve.
