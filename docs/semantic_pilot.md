# Preparação do piloto semântico humano

## Estado da proveniência e elegibilidade

A entrada foi o conjunto fixo de 19 pares `VALIDATED` em `pilot_pairs_validated.csv`. Uma segunda passagem documental conferiu, em cada um dos 38 lados, a associação temática ao evento oficial, a data no CSV da Câmara, o ator e seu marcador, os offsets da fala e do trecho, e o suporte da manifestação central do resumo LDS. O julgamento está em `provenance_review_2.csv`; ele **não alterou** `pilot_evidence_review.csv` nem `pilot_pairs_validated.csv`. O revisor foi o Codex em uma nova passagem sobre as fontes. Isso reduz dependência da primeira planilha, mas **não equivale a uma segunda pessoa humana independente**.

Em 37 lados as duas passagens concordam como válidas (`AGREE_VALID`); em 1 há `DISAGREE`. O lado A de Mercedes Bustamante, registro 188, contém um resumo LDS que afirma 38% no doutorado e 54% no pós-doutorado. A transcrição não fornece 38% e associa 54% a cargos e funções na CAPES; o span selecionado confirma apenas 42% de docentes mulheres na pós-graduação. O par ficou fora do piloto semântico e exige adjudicação documental própria. Não há `AGREE_INVALID` nem `UNKNOWN` entre os 38 lados revisados. O algoritmo e os dois julgamentos por dimensão estão em `provenance_agreement.csv`.

Restam **18 pares preliminarmente elegíveis**, listados em `semantic_pilot_eligible_pairs.csv`. O filtro exige `VALIDATED` na primeira etapa e `AGREE_VALID` em **ambos** os lados após a segunda. A lista não é gold e não contém resposta semântica. São 31 eventos distintos nos 18 pares.

## Recorte de eventos

O universo inicial são os eventos parlamentares do PublicHearingBR, incluindo comparecimento de ministro, audiência com deliberação e seminário. Os códigos preservados em `event_a/b` e em `event_type_code_a/b` do arquivo de referência são:

| Código | Lados nos 19 iniciais | Lados nos 18 elegíveis |
|---|---:|---:|
| `PUBLIC_HEARING` | 29 | 27 |
| `MINISTER_APPEARANCE` | 6 | 6 |
| `PUBLIC_HEARING_WITH_DELIBERATION` | 2 | 2 |
| `SEMINAR` | 1 | 1 |

Há **13 pares elegíveis** em que os dois eventos são audiências públicas, incluindo audiência com deliberação. Essa será uma análise de sensibilidade posterior; os outros cinco não são descartados automaticamente.

## Arquivos e campos de anotação

`semantic_pilot_annotator_1.csv` e `semantic_pilot_annotator_2.csv` contêm os mesmos 18 `pair_id` com ordem diferente. Para cada posição visual `a/b`:

| Grupo | Campos | Significado |
|---|---|---|
| Metadados cegos | `event_a/b`, `date_a/b`, `topic_a/b` | Tipo normalizado, data oficial e assunto LDS |
| Texto | `text_a/b`, `context_before_a/b`, `evidence_a/b`, `context_after_a/b` | Turno original completo e sua divisão literal em contexto/trecho/contexto |
| Cegamento | `blinding_warning` | Possível identificação incidental no texto original |
| Etapa 1 | `stance_determinable_a/b` | `YES`, `NO`, `UNCERTAIN` |
| Etapa 2 | `target_proposition_a/b` | Proposição curta, específica e neutra, em texto livre |
| Etapa 3 | `same_proposition` | `YES`, `NO`, `UNCERTAIN`; apenas se ambos os lados receberam determinabilidade `YES` |
| Etapa 4 | `stance_a/b` | `FAVOR`, `AGAINST`, `UNCERTAIN` em relação à proposição própria |
| Confiança | `determinability_confidence_a/b`, `proposition_confidence_a/b`, `comparability_confidence`, `stance_confidence_a/b` | `LOW`, `MEDIUM`, `HIGH` para decisões aplicáveis |
| Justificativas | `annotation_notes_a/b`, `comparability_notes` | Texto opcional; pedir nota curta em incerteza, baixa confiança ou dificuldade |

Todos os 17 campos de resposta começam vazios. A referência `semantic_pilot_reference.csv` contém IDs locais e oficiais, ator, cargos, resumos LDS, fonte e offsets de fala/evidência, primeira validação, segundo julgamento, tema e mapeamento das posições visuais para os lados cronológicos. Ela deve ficar fora da visão dos anotadores.

## Cegamento, contexto e randomização

As planilhas cegas não têm colunas estruturadas de nome, partido, UF, cargo, ID de evento ou stance silver. `text_a/b` preserva o turno original completo; `context_before + evidence + context_after` o reconstitui sem edição. Assim, não foi preciso amputar o contexto para apresentar o trecho. Identificações ditas na própria fala continuam possíveis. Todas as 18 linhas têm alerta de possível cargo político no texto; 6 também têm alerta de possível nome do ator e 4 de possível partido. Os alertas são heurísticos e podem incluir falso positivo; nenhum texto foi alterado para ocultar nomes.

As sementes fixas são **4311** para anotador 1 e **9877** para anotador 2. A ordem dos pares difere; 8 pares foram apresentados com B cronológico primeiro no arquivo 1 e 5 no arquivo 2. `chronological_source_side` e `annotator_1/2_display_a_source_side` na referência preservam a reconstrução temporal. As datas continuam visíveis, pois são contexto necessário para a tarefa.

## Relação derivada e concordância futura

`derive_relation` em `src/voxlab/agreement.py` é função pura:

| Condição, em ordem de precedência | Resultado |
|---|---|
| Ao menos um `stance_determinable=NO` | `INSUFFICIENT_EVIDENCE` |
| Determinabilidade `UNCERTAIN`/ausente em qualquer lado | `RELATION_UNCERTAIN` |
| Ambos `YES`, `same_proposition=NO` | `INCOMPARABLE` |
| Ambos `YES`, `same_proposition=UNCERTAIN`/ausente | `RELATION_UNCERTAIN` |
| Mesma proposição, stance indefinida em algum lado | `RELATION_UNCERTAIN` |
| Mesma proposição, `FAVOR/FAVOR` ou `AGAINST/AGAINST` | `STANCE_MAINTAINED` |
| Mesma proposição, `FAVOR/AGAINST` ou `AGAINST/FAVOR` | `STANCE_REVERSED` |

Não há coluna de relação final para o anotador. O script de concordância reconstrói os lados cronológicos antes de comparar os CSVs e calcula, **somente após ambos completos**, concordância bruta, Kappa de Cohen, distribuição de classes e alertas de prevalência para: determinabilidade, comparabilidade, stance e relação derivada. Comparabilidade é medida onde ambos os anotadores consideraram os dois lados determináveis; stance, onde ambos consideraram o lado determinável. Isso evita tratar resposta não aplicável como classe. `target_proposition` permanece texto livre para comparação manual posterior; não há Kappa de strings nem equivalência por embedding.

**Atualização de 2026-09-23:** as duas pessoas preencheram as planilhas, o consenso foi validado e o gold do piloto foi gerado. Os resultados finais e a decisão científica estão em `docs/semantic_consensus_analysis.md`. Esta seção preserva o desenho anterior ao recebimento das respostas.

## Reprodução e proteção das respostas

Na raiz do repositório:

```bash
PYTHONPATH=src python3 -m voxlab.semantic_pilot
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

O gerador lê o segundo julgamento já registrado, compara as revisões e monta as planilhas. **Não execute o gerador após o preenchimento humano:** ele interrompe a execução ao encontrar respostas para preservá-las. Para analisar as planilhas preenchidas, use `PYTHONPATH=src python3 -m voxlab.agreement`. A [guideline](annotation_guideline.md) registra as instruções e os casos especiais usados pelos anotadores.
