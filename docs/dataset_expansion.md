# Expansão do dataset: segunda rodada de candidatos

**Estado desta fase (2026-09-23):** candidatos estratificados gerados. Aguarda revisão humana de proveniência antes da preparação dos pacotes de anotação semântica.

## 1. Universo inicial

O corpus PublicHearingBR_LDS.jsonl contém 206 registros. O pipeline de auditoria (`audit.py`) já havia identificado:

| Medida | Valor |
|---|---:|
| Registros totais | 206 |
| Atores normalizados distintos | 878 |
| Atores em ≥2 registros | 102 |
| Pares do mesmo ator com datas distintas | 396 |
| Pares com TF-IDF ≥ 0,10 (threshold atual) | 58 |
| Pares no piloto original | 25 |
| Pares no gold humano | 18 |

Os números acima foram recalculados e estão consistentes com `data/processed/audit_summary.json`.

## 2. Filtros aplicados na expansão

### Exclusão do gold pilot

Os 18 pares de `data/annotations/semantic_pilot_gold.csv` não podem ser selecionados novamente. A exclusão opera em dois níveis:

1. Por `pair_id` direto.
2. Por par canônico de audiências `{actor_id|hearing_id_a, actor_id|hearing_id_b}` — detecta a inversão A-B / B-A mesmo que resulte em um `pair_id` diferente.

**Resultado:** 40 candidatos elegíveis (58 − 18 gold).

Nota: os 7 pares do piloto que não chegaram ao gold (4 PARTIALLY_VALIDATED, 2 INVALID, 1 excluído na 2ª revisão) **não** são automaticamente excluídos — o critério é apenas o gold. Esses 7 estão presentes nos 40 restantes se tiverem pair_id diferente dos 18 gold pair_ids.

### Estratificação por similaridade temática

Os estratos são derivados da distribuição real dos 40 candidatos elegíveis usando quantis:

| Estrato | Percentil | Pares no pool |
|---|---|---:|
| LOW | 0–60% | 24 |
| MEDIUM | 60–90% | 12 |
| HIGH | 90–100% | 4 |

Os limites reais de similaridade TF-IDF na distribuição dos 40:
- LOW: 0,101 – 0,148
- MEDIUM: 0,149 – 0,263
- HIGH: 0,264 – 1,000

Nenhum threshold numérico fixo foi imposto; os limites emergem da distribuição observada.

### Estratificação temporal

| Estrato | Intervalo (gap_publication_days) | Pares no pool |
|---|---|---:|
| SHORT | 0–30 dias | 9 |
| MEDIUM | 31–180 dias | 21 |
| LONG | >180 dias | 10 |

Datas usadas: `publication_date_a` e `publication_date_b` (data de publicação do artigo, não data de audiência verificada). Nenhuma data de audiência oficial está disponível nesta etapa.

### Cap por ator

Máximo de 2 pares por ator na amostra de expansão. Critério de seleção dentro do cap: maior similaridade TF-IDF; empate desfeito por maior intervalo temporal; empate final por pair_id (determinístico).

| Ator | Pares no pool | Pares selecionados | Excluídos pelo cap |
|---|---:|---:|---:|
| Erika Kokay | 6 | 2 | 4 |
| Alexandre da Silva | 3 | 2 | 1 |
| Gilson Daniel | 3 | 2 | 1 |
| Demais atores | ≤2 cada | igual | 0 |

**Resultado após cap:** 34 pares selecionados de 27 atores distintos.

## 3. Método de retrieval

**Apenas TF-IDF lexical**, idêntico ao piloto original (`audit.py:tfidf_vectors`). Embeddings neurais não foram implementados nesta etapa.

**Justificativa:** com 40 candidatos no pool e 206 registros no corpus, a diferença de recall entre TF-IDF e embeddings seria estatisticamente não interpretável. A complexidade adicional de dependência, cache e reprodutibilidade não se justifica. Se o corpus for expandido com mais audiências, reavaliar.

## 4. Distribuição final da amostra de expansão

34 pares de 27 atores:

| Similarity stratum | Pares |
|---|---:|
| LOW (0,101–0,148) | ~20 |
| MEDIUM (0,149–0,263) | ~11 |
| HIGH (0,264–1,000) | ~3 |

| Temporal stratum | Pares |
|---|---:|
| SHORT (0–30d) | ~7 |
| MEDIUM (31–180d) | ~19 |
| LONG (>180d) | ~8 |

Atores do gold pilot presentes na expansão: 8 de 18 (atores com pares remanescentes após o gold).
Atores inteiramente novos (não no gold): 19 de 27.

## 5. Sanity check retrospectivo do piloto

Para verificar o recall do retriever TF-IDF, calculamos retrospectivamente se cada um dos 18 pares gold teria sido recuperado ao threshold atual de 0,10.

**Resultado: 18/18 pares gold recuperados ao threshold 0,10.** O retriever não perdeu nenhum par que chegou ao gold humano. Isso valida o threshold atual para o tamanho deste corpus.

**Importante:** o resultado do sanity check não foi usado para escolher ou ajustar thresholds para os novos candidatos. Thresholds são parâmetro de retrieval, não de otimização por rótulo.

## 6. Riscos de viés de seleção

- **Concentração por ator:** Erika Kokay tinha 6 pares no pool (15%). O cap de 2 por ator mitigou isso, mas ela ainda aparece 2 vezes na expansão, o que excede a maioria dos atores.
- **Temas parlamentares recorrentes:** pares de alta similaridade (HIGH stratum) provavelmente compartilham tópicos muito específicos, o que pode facilitar a anotação mas reduzir diversidade temática.
- **Identidade por nome normalizado:** o `actor_id` é derivado por normalização de acento/caixa, sem verificação de identidade humana. Homônimos podem ser agrupados incorretamente. A revisão de proveniência deve verificar identidade para cada par.
- **Datas de publicação como proxy:** `publication_date` não é a data da audiência. A ordem temporal de `a` e `b` foi derivada das datas de publicação dos artigos e está marcada como `temporal_order_verified=false` em todos os candidatos. A revisão de proveniência deve verificar datas oficiais.
- **Disponibilidade desigual de falas:** o parser de turnos extrai falas apenas quando o nome do orador aparece explicitamente na transcrição. Atores sem marcador de turno claro podem não ter evidência literal rastreável.
- **Ausência de STANCE_REVERSED no gold:** nenhum dos 18 pares gold apresentou reversão. Isso não prova que reversão é rara no corpus — pode ser um artefato do piloto pequeno. A expansão não deve ser orientada para buscar reversões; elas devem emergir da anotação humana se existirem.

## 7. Seeds e reprodutibilidade

O cap por ator é determinístico (sort por similarity desc, delta desc, pair_id asc — sem random). Não há seeds a documentar para esta etapa. O módulo pode ser reproduzido com:

```bash
PYTHONPATH=src python3 -m voxlab.expansion
```

## 8. Artefatos produzidos

| Arquivo | Descrição |
|---|---|
| `data/processed/expansion_candidate_pairs.csv` | 58 linhas: 34 elegíveis, 6 excluídos pelo cap, 18 gold-excludidos |
| `data/processed/expansion_funnel.json` | Funil completo com contagens e sanity check |
| `data/annotations/expansion_provenance_review.csv` | Revisão humana dos 34 pares, com IDs e índices da fonte, resumos LDS e campos documentais completos |
| `data/processed/expansion_provenance_readiness.csv` | Diagnóstico por par, status derivado e problemas de integridade |
| `data/processed/expansion_provenance_readiness.json` | Contagens e decisão de prontidão da segunda rodada |
| `data/processed/expansion_reusable_provenance.csv` | Oito manifestações idênticas já validadas no primeiro piloto, presentes em sete pares novos |
| `data/processed/expansion_speech_candidates.csv` | 340 sentenças literais ranqueadas em turnos nominais; auxilia revisão, sem status de evidência validada |

## 9. Próxima etapa (Fase B — aguarda humano)

A revisão de proveniência em `expansion_provenance_review.csv` é uma etapa humana. As colunas `source_record_id_*`, `source_actor_index_*`, `source_opinion_index_*` e `source_summary_*` são preenchidas pelo pipeline e não devem ser alteradas. Para cada um dos 34 pares elegíveis, um revisor deve:

1. Localizar os dois eventos nas fontes oficiais (CSVs da Câmara em `data/raw/official_events/`).
2. Preencher os metadados oficiais `event_id/source/type/description/start/date_*` e confirmar `event_verified_*` e `date_verified_*`.
3. Registrar o marcador nominal do ator e confirmar `actor_marker_verified_*` e `turn_attribution_verified_*`.
4. Copiar a fala e a evidência literais para `speech_text_*` e `evidence_text_*`, com offsets absolutos de início e fim na transcrição. A evidência deve estar contida na fala.
5. Confirmar identidade do ator entre as duas aparições (`same_actor_verified`, `actor_identity_basis`).
6. Julgar se a evidência sustenta o resumo LDS em `summary_support_reviewed_*`, registrar revisor e notas, e preencher `validation_status`.

Ao executar `python3 -m voxlab.expansion`, o validador reconstrói fala e evidência pelos offsets, confere se o trecho pertence a um turno nominal do ator, valida IDs e datas nos CSVs oficiais e deriva um status independente. Se alguma resposta humana já tiver sido preenchida, o gerador preserva o arquivo existente e segue somente com a validação.

### Estado da revisão recebida em 2026-09-24

O arquivo recebido contém os 34 pares esperados e nenhum duplicado. A validação confirmou:

- 68 lados com IDs e metadados de eventos oficiais consistentes;
- 68 falas e evidências reconstruídas literalmente pelos offsets;
- 68 trechos dentro de turnos nominais compatíveis com o ator;
- 34 pares com eventos oficiais distintos e ordem temporal correta;
- nenhuma inversão entre os lados `earlier` e `later`.

As descrições oficiais armazenadas no CSV usam `LF`, enquanto os snapshots da Câmara preservam `CRLF`. O validador passou a normalizar apenas essa diferença de fim de linha. Também foram documentadas quatro variantes nominais encontradas nos marcadores das transcrições: Nísia Trindade, Ricardo Galvão, Rodrigo Agostinho e Roselene Alves.

A revisão ainda não está completa: `same_actor_verified` e `actor_identity_basis` estão vazios nos 34 pares. Por isso, as 29 linhas declaradas `VALIDATED` são derivadas como `PARTIALLY_VALIDATED`. As duas linhas `INVALID` e as três `PARTIALLY_VALIDATED` permanecem coerentes com as decisões humanas sobre suporte do resumo, mas também precisam dos dois campos de identidade. O diagnóstico por par está em `data/processed/expansion_provenance_readiness.csv`.

Uma leitura conservadora das notas recomenda ainda revisar três lados marcados como suportados. Em `597ab529d9e58c55` (Nísia Trindade, `later`), o próprio revisor informa que o valor de R$ 86 milhões do resumo não foi localizado, e a evidência selecionada mostra apenas a reabertura de 321 leitos. Em `99ca50f2ecb70ba4` (Rodrigo Agostinho, `later`), a negação de perseguição está em outro turno, fora da fala e evidência registradas. Em `8034e650e53050e1` (Tarcísio Motta, `later`), a menção explícita à PEC 44/2023 também foi localizada fora do span selecionado. Esses apontamentos não substituem o julgamento humano: o revisor deve decidir se o trecho atual sustenta a manifestação central ou se fala, evidência e status precisam ser corrigidos.

Depois do preenchimento de identidade, as três linhas ainda parciais devem receber uma decisão final documentada: corrigir evidência e suporte quando houver base ou classificá-las como `INVALID`. Os pacotes semânticos permanecem bloqueados até que cada linha seja `VALIDATED` ou `INVALID` e pelo menos 20 pares sejam válidos.

Antes de pesquisar um lado do zero, o revisor deve consultar `expansion_reusable_provenance.csv`. Seus oito registros correspondem exatamente ao mesmo triplo de registro, ator e opinião já validado no primeiro piloto. Para os outros lados, `expansion_speech_candidates.csv` fornece até cinco sentenças por manifestação, ranqueadas por sobreposição lexical com o resumo LDS. Esses candidatos continuam sendo heurísticos e precisam de julgamento humano sobre atribuição e suporte.

Somente pares com `validation_status=VALIDATED` avançam para a preparação de pacotes de anotação semântica (Fase B).

O mínimo operacional desta rodada foi fixado em **20 pares validados**, coerente com o tamanho de piloto definido no planejamento original. `READY_FOR_EXPANSION_ANNOTATION` exige que todos os 34 pares tenham uma decisão final (`VALIDATED` ou `INVALID`), que não existam falhas de integridade e que pelo menos 20 sobrevivam. O limiar é operacional para decidir se vale montar uma nova rodada; ele não é uma estimativa de poder estatístico.

A decisão após a revisão será uma de:
- `READY_FOR_EXPANSION_ANNOTATION` — pares suficientes validados
- `PROVENANCE_REVIEW_REQUIRED` — revisão incompleta ou inconclusiva
- `INSUFFICIENT_EXPANSION_CANDIDATES` — pool validado menor que o mínimo aceitável

### Atualização: checagem de identidade conectada ao pipeline

O passo de identidade (`same_actor_verified`/`actor_identity_basis`) nunca chegou a ser um campo de preenchimento humano do zero: desde o piloto original, ele é derivado por `provenance.identity_status()` — uma heurística conservadora de nome + cargo/UF. Essa chamada não estava conectada em `expansion.py`; `apply_conservative_identity_check()` corrige a lacuna, preenchendo os dois campos somente quando estão vazios ou ainda carregam a própria saída "unknown" da função (nunca um valor `true`/`false` ou uma justificativa em texto livre escrita por humano).

`identity_status()` também recebeu uma regra nova: cargo idêntico (normalizado) nos dois lados confirma identidade (`same_full_name_and_identical_role_description`), o mesmo padrão já usado para UF e para o dicionário de instituições. Isso resolveu 4 dos 10 pares antes marcados `unknown` (Nísia Trindade, Ricardo Galvão, Rodrigo Agostinho e uma aparição de Alexandre da Silva).

Estado após reprocessamento: **23 VALIDATED**, 9 `PARTIALLY_VALIDATED`, 2 `INVALID`. Ainda `PROVENANCE_REVIEW_REQUIRED` — a decisão exige que todos os 34 pares cheguem a um estado final, não apenas que 20 sejam validados. Os 9 pares restantes precisam de julgamento humano genuíno:

- **6 com identidade ambígua** (cargo similar mas não idêntico — requer julgar se são o mesmo cargo/instituição): `370ab0f946469bab`, `e13d509a937ffa5f`, `ffe531755c6def2e`, `406f53bbc7b4086a`, `b4a84fb6380ec371`, `8c2dfcbfad142a02`.
- **3 com identidade confirmada mas evidência pendente** (o revisor já marcou `evidence_verified=unknown`): `e8fa709c49d4cf21`, `7d09d414bbbcee5f`, `d336204af6200b5c`.

Esses 9 não foram resolvidos automaticamente por decisão deliberada: julgar se cargos com fraseados diferentes referem-se à mesma posição, ou se um trecho de transcrição sustenta um resumo, é exatamente o tipo de julgamento semântico que este projeto reserva para revisão humana — não para heurística determinística nem para leitura de LLM.

### Atualização: revisão de proveniência concluída (2026-09-24)

Gabriel resolveu os 6 pares de identidade ambígua manualmente, com justificativa documentada por par (incluindo um caso de troca de entidade — Paulo Xavier, FEMBRAPP→FANMA — confirmado por continuidade de discurso e coerência com a lista oficial do evento posterior). Os 3 pares de evidência pendente (Padre João, Priscila Costa, Vanessa Pirolo) revelaram divergências factuais reais entre o resumo LDS e a transcrição literal (valores numéricos trocados, detalhes de registros diferentes atribuídos ao par errado) — foram marcados `INVALID` em 2026-09-24, com `summary_support_reviewed`/`evidence_verified=false` no(s) lado(s) afetado(s).

Estado final: **29 VALIDATED, 5 INVALID**, 0 pares pendentes, 0 divergências entre declarado e derivado. `decision: READY_FOR_EXPANSION_ANNOTATION`. A Fase B (preparação dos pacotes cegos para os dois anotadores) pode começar.

### Fase B: pacotes de anotação semântica gerados (2026-09-24)

`src/voxlab/expansion_semantic_pilot.py` reaproveita, sem duplicar, a lógica exata do piloto original: filtra os pares com `derived_validation_status=VALIDATED` em `expansion_provenance_review.csv`, renomeia os campos `earlier`/`later` para o formato `a`/`b` do piloto (`reshape_to_pilot_pair`) e então chama `semantic_pilot.annotation_rows` sem alterações — mesmo esquema de cegamento, mesmas seeds por anotador (`SEEDS = {1: 4311, 2: 9877}`), mesma taxonomia de resposta.

Artefatos gerados:
- `data/annotations/expansion_annotator_1.csv` e `expansion_annotator_2.csv`: 29 pares cada, mesma composição, ordem e apresentação A/B embaralhadas independentemente, todas as respostas em branco.
- `data/annotations/expansion_semantic_pilot_reference.csv`: mapeamento de apresentação por anotador e lado cronológico de origem — não deve ser aberto pelos anotadores.

84/84 testes passam, incluindo verificação de que os 5 pares `INVALID` nunca chegam aos pacotes, de que nenhum campo silver/gold aparece nos arquivos de anotação e de que o relatório de prontidão registra a geração dos pacotes. A tarefa dos anotadores segue `docs/annotation_guideline.md`.
