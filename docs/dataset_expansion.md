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
| `data/annotations/expansion_provenance_review.csv` | Template para revisão humana dos 34 pares elegíveis; campos de revisão em branco |

## 9. Próxima etapa (Fase B — aguarda humano)

A revisão de proveniência em `expansion_provenance_review.csv` é uma etapa humana. Para cada um dos 34 pares elegíveis, um revisor deve:

1. Localizar os dois eventos nas fontes oficiais (CSVs da Câmara em `data/raw/official_events/`).
2. Preencher `event_id_earlier`, `event_id_later`, `event_date_earlier`, `event_date_later`.
3. Verificar se o ator aparece na transcrição de cada evento (`event_verified_*`).
4. Localizar e extrair a fala literal atribuída ao ator (`speech_verified_*`, `evidence_verified_*`).
5. Confirmar identidade do ator entre as duas aparições (`same_actor_verified`, `actor_identity_basis`).
6. Preencher `validation_status` como `VALIDATED`, `PARTIALLY_VALIDATED` ou `INVALID`.

Somente pares com `validation_status=VALIDATED` avançam para a preparação de pacotes de anotação semântica (Fase B).

A decisão após a revisão será uma de:
- `READY_FOR_EXPANSION_ANNOTATION` — pares suficientes validados
- `PROVENANCE_REVIEW_REQUIRED` — revisão incompleta ou inconclusiva
- `INSUFFICIENT_EXPANSION_CANDIDATES` — pool validado menor que o mínimo aceitável
