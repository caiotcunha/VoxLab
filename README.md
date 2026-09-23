# VoxLab: viabilidade de análise longitudinal de postura

Pergunta desta etapa: o PublicHearingBR contém recorrência do mesmo ator em audiências relacionadas suficiente para justificar uma investigação sobre manutenção e reversão de postura? A hipótese é que verificar a comparabilidade de duas proposições antes de comparar polaridades reduz falsas reversões. O gate automático ainda não foi implementado; o protocolo, os baselines determinísticos e a ablação sem gate já estão reproduzíveis.

## Estado dos dados e ressalvas

O repositório contém 206 registros LDS com `id`, `materia`, `metadados` (`assunto`, `envolvidos`) e `transcricao`; o NLI contém os mesmos IDs e metadados extraídos alternativos. `base_posturas_classificadas.csv` foi produzido por `nunes.ipynb`: um LLM extraiu proposições por registro e classificou pares opinião–proposição. São **rótulos silver**, sem validação humana. O piloto agora possui gold humano independente e adjudicado; uma avaliação final ainda exige ampliar esse gold e reservar exemplos que não participem do desenvolvimento.

O campo `materia` contém **data de publicação da notícia**, que não comprova a data da audiência. A coluna `hearing_date` permanece vazia. `hearing_id` nos arquivos processados é o ID do registro original, sem verificação de que cada registro representa uma única audiência. `speech_text` guarda resumos de opinião do LDS, não fala literal; `evidence` fica vazia e `evidence_status` explicita a falta de verificação. Cada resumo pode ser rastreado pelos índices de ator e opinião no JSONL. Os pares são somente **candidatos exploratórios**, ordenados pela data de publicação, com `temporal_order_verified=false`.

## Reprodução

Requer Python 3.10+; a auditoria usa apenas a biblioteca padrão, sem chamadas de API ou instalação de dependências. A partir da raiz `VoxLab/`:

```bash
PYTHONPATH=src python3 -m voxlab.audit
PYTHONPATH=src python3 -m voxlab.provenance
PYTHONPATH=src python3 -m voxlab.agreement
PYTHONPATH=src python3 -m voxlab.consensus
PYTHONPATH=src python3 -m voxlab.expansion
PYTHONPATH=src python3 -m voxlab.comparability_baselines
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Os parâmetros `--threshold` (padrão 0.10), `--top-k` (5 pares de audiência posterior por audiência inicial e ator) e `--pilot-size` (25) são explícitos. Exemplo: `PYTHONPATH=src python3 -m voxlab.audit --threshold 0.2`. Use `--root` para indicar outra cópia dos arquivos brutos. O padrão 0.10 serve para triagem humana, não é um corte de comparabilidade. A análise de sensibilidade, incluindo contagens antes do limite top-k, aparece em `data/processed/audit_summary.json`. A seleção do piloto é determinística, sem usar rótulos silver. A validação lê os três CSVs oficiais preservados em `data/raw/official_events/`, o cruzamento manual de eventos e a revisão de evidências. Veja `docs/provenance_validation.md`.

## Arquivos

- `src/voxlab/audit.py`: carga, tabela longitudinal, estatísticas, TF-IDF local dos assuntos, candidatos e amostra piloto.
- `data/processed/longitudinal.csv`: resumos com proveniência do LDS; proposições e posturas, quando presentes, são silver.
- `data/processed/candidate_pairs.csv`: um par de resumos por par ator–registros relacionados, selecionado por sobreposição lexical; nenhuma comparabilidade foi rotulada.
- `data/processed/audit_summary.json`: números observados, derivados e heurísticos.
- `data/annotations/pilot_pairs.csv`: amostra com proveniência para reconstrução.
- `data/annotations/pilot_pairs_blind.csv` e `pilot_annotation_template.csv`: versão parcialmente cega e campos de anotação.
- `docs/annotation_guideline.md`: árvore de decisão e exigências de verificação.
- `docs/current_state.md`: auditoria do projeto preexistente e limitações.
- `src/voxlab/provenance.py`: validação documental, parsing de turnos e alinhamento NLI–transcrição.
- `data/annotations/pilot_event_crosswalk.csv`, `pilot_evidence_review.csv` e `pilot_pairs_validated.csv`: decisões revisáveis e 25 pares com status.
- `data/processed/provenance_schema.csv`, `pilot_nli_spans.csv`, `pilot_speech_candidates.csv` e `provenance_funnel.json`: diagnóstico e funil.
- `data/raw/official_events/SOURCES.md`: origem e hashes dos metadados da Câmara.
- `docs/provenance_validation.md`: método e resultados da validação documental.
- `src/voxlab/semantic_pilot.py` e `agreement.py`: preparação cega do piloto e análise de concordância.
- `data/annotations/provenance_review_2.csv`, `provenance_agreement.csv` e `semantic_pilot_eligible_pairs.csv`: segunda passagem documental, comparação e elegibilidade.
- `data/annotations/semantic_pilot_annotator_1.csv`, `semantic_pilot_annotator_2.csv` e `semantic_pilot_reference.csv`: duas anotações independentes preenchidas e referência identificada.
- `docs/semantic_pilot.md`: desenho, recorte, randomização e estado do piloto humano.
- `data/processed/semantic_agreement.json`, `data/annotations/semantic_annotation_comparison.csv` e `semantic_adjudication_queue.csv`: concordância das duas anotações e fila produzida antes do consenso.
- `docs/semantic_agreement.md`: resultados observados, limites e instruções de adjudicação.
- `data/annotations/semantic_pilot_consensus.csv`, `semantic_consensus_comparison.csv` e `data/processed/semantic_consensus_analysis.json`: consenso humano, validação e distribuições finais.
- `data/annotations/semantic_pilot_gold.csv`: 18 pares adjudicados, cronológicos e rastreáveis ao hash do consenso humano.
- `src/voxlab/consensus.py` e `docs/semantic_consensus_analysis.md`: validação, geração do gold e decisão científica.
- `src/voxlab/expansion.py` e `docs/dataset_expansion.md`: expansão do corpus, funil de candidatos e template de revisão de proveniência para a segunda rodada.
- `data/processed/expansion_candidate_pairs.csv` e `expansion_funnel.json`: 34 pares elegíveis (de 40 disponíveis após excluir o gold) com estratificação por similaridade e gap temporal.
- `data/annotations/expansion_provenance_review.csv`: template rastreável para revisão humana de proveniência dos 34 candidatos; inclui fonte, texto, offsets e metadados oficiais.
- `data/processed/expansion_provenance_readiness.csv` e `.json`: validação de offsets, atribuição, eventos, cronologia e prontidão para a segunda anotação.
- `data/processed/expansion_reusable_provenance.csv` e `expansion_speech_candidates.csv`: oito lados previamente validados e 300 candidatos literais para acelerar a revisão humana.
- `src/voxlab/comparability_baselines.py` e `docs/comparability_experiment.md`: protocolo, métricas, baselines sem API e análise da ablação sem gate.
- `data/processed/comparability_pilot_baselines.json`, `comparability_pilot_diagnostics.csv` e `semantic_pilot_gold_manifest.json`: resultados exploratórios, diagnóstico por par e congelamento do gold.
- `datasetCaio.ipynb`, `nunes.ipynb` e `dashboard_polarizacao_completa.html`: exploração anterior preservada; o dashboard não representa o resultado longitudinal.

O notebook antigo `nunes.ipynb` ainda requer `langchain-core`, `langchain-nvidia-ai-endpoints`, `pandas`, `tqdm`, `networkx` e `pyvis` para suas próprias células. Essas dependências **não** fazem parte da nova auditoria nem são executadas por ela. `NVIDIA_API_KEY` deve ser fornecida pelo ambiente para executar as células antigas. Não é necessária para reproduzir esta etapa.

## Resultado da auditoria inicial e do piloto documental

No LDS, 102 de 878 nomes normalizados aparecem em dois ou mais registros. Existem 58 pares candidatos com similaridade de assunto ≥0,10 e datas de publicação distintas; 25 foram selecionados para o piloto. A primeira validação documental confirmou 19 pares, e uma segunda passagem deixou **18 pares** para duas anotações humanas. Ambas foram entregues e o consenso final passou por validação integral. O gold humano contém 5 `STANCE_MAINTAINED`, 11 `INCOMPARABLE`, 2 `RELATION_UNCERTAIN` e 0 `STANCE_REVERSED`. Há **GO limitado para estudar o comparability gate**, mas a amostra é pequena demais para uma avaliação final e não permite alegar detecção de reversão. Veja `docs/semantic_consensus_analysis.md`.

## Expansão do corpus

Excluídos os 18 pares gold, restam **40 candidatos** no pool. Aplicado cap de 2 pares por ator (principalmente Erika Kokay ×6, Alexandre da Silva ×3, Gilson Daniel ×3), a amostra de expansão tem **34 pares de 27 atores**. O sanity check retrospectivo confirma que o retriever TF-IDF recuperaria todos os 18 pares gold ao threshold 0,10. O template rastreável e seu validador estão prontos; os 34 pares permanecem `UNRESOLVED` até a revisão documental humana. Veja `docs/dataset_expansion.md`.

## Baselines exploratórios

Nos 16 pares com decisão binária, o corte de recuperação TF-IDF ≥0,10 classifica todos como comparáveis: recupera os 5 positivos, mas produz 11 falsos positivos. Sem o gate, a comparação direta das stances humanas emitiria relação para os 18 pares, incluindo 13 relações indevidas e 2 falsas reversões. Esses resultados são de desenvolvimento, não de teste final. Veja `docs/comparability_experiment.md`.
