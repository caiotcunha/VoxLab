# Validação documental dos 25 pares piloto

## Escopo e fontes

Esta etapa revisou os 206 registros de cada JSONL e validou a cadeia documental do piloto fixo de 25 pares, 41 registros LDS distintos. Não atribuiu comparabilidade nem mudança de postura. `base_posturas_classificadas.csv` contém rótulos automáticos; os campos `verificacao_alucinacao` do NLI contêm julgamentos de modelos e um indicador `verificacao_manual` cuja metodologia não foi verificada nesta etapa. Nenhum deles foi usado como verdade documental. Os metadados oficiais e seus hashes estão em `data/raw/official_events/SOURCES.md`.

## Schema e identificadores

`data/processed/provenance_schema.csv` lista **todos** os 78 caminhos encontrados nos 206 objetos LDS e nos 206 NLI, com `field`, `presence_count`, `example_type` e `possible_semantic_role`. A contagem é por registro que contém o caminho, inclusive para caminhos `[]`; não é o número de elementos das listas.

| Dataset/campo | Presença | Tipo | Uso e limite |
|---|---:|---|---|
| LDS `id` | 206 | int | ID local do registro, sequencial de 1 a 206; não é ID de evento |
| LDS `materia` | 206 | str | Notícia, inclusive data de publicação |
| LDS `metadados.assunto` | 206 | str | Assunto para busca de candidatos |
| LDS `metadados.envolvidos[].nome/cargo` | 206 | str | Nome e cargo para desambiguação |
| LDS `metadados.envolvidos[].opinioes[]` | 206 | str | Resumo de opinião; não é citação |
| LDS `transcricao` | 206 | str | Texto da fala original e seus marcadores |
| NLI `id` | 206 | int | Mesmo ID local do LDS |
| NLI `metadados_extraidos.assunto/tl_dr` | 206 | str | Resumos automáticos |
| NLI `metadados_extraidos.envolvidos[].nome/cargo` | 206 | str | Atores extraídos; listas não alinhadas às do LDS |
| NLI `metadados_extraidos.envolvidos[].opinioes[].opiniao` | 206 | str | Resumo automático, diferente do LDS |
| NLI `metadados_extraidos.envolvidos[].opinioes[].chunks_proximos[]` | 206 | str | Candidato a trecho de transcrição |
| NLI `...verificacao_alucinacao` | 206 | dict | Julgamentos e indicador de revisão; não usados como prova nesta etapa |

Não há campo estruturado `hearing_id`, `event_id`, `meeting_id`, data de audiência ou URL da audiência em qualquer dos dois JSONL. URLs ocasionais dentro da notícia/transcrição não formam chave de evento. Os IDs 1–206 são chaves locais compartilhadas pelos JSONL; seu formato não autoriza tratá-los como IDs oficiais. Não existe, portanto, junção determinística direta registro → evento nos arquivos de origem.

## Eventos, datas e atores

O arquivo `pilot_event_crosswalk.csv` registra a associação manual de 41 IDs locais a 41 eventos oficiais distintos. O pareamento usa assunto, comissão, números de requerimento, convidados, ministro e/ou texto de abertura, conforme `match_basis` e `review_note`. `pilot_pairs_validated.csv` guarda por lado o ID, URI, tipo, descrição e início do evento, além da fonte da data. Só eventos com metadados oficiais e situação encerrada recebem `event_verified=true` e `hearing_date_verified=true`. Os tipos oficiais são 34 audiências públicas, 4 reuniões de comparecimento de ministro, 2 audiências públicas com deliberação e 1 seminário (registro local 17); portanto a unidade confirmada é **evento**, nem sempre audiência no sentido estrito. O CSV oficial fornece `descricao`, mas não um campo de título; `event_title` permanece vazio.

`publication_date` vem de `materia` e é data da notícia. `hearing_date` vem exclusivamente de `dataHoraInicio` oficial; o código nunca copia a primeira para a segunda. O mesmo valor está em `event_date`, nome mais exato para o seminário e os comparecimentos de ministro. Nas 50 manifestações, a publicação ocorreu de 0 a 2 dias após o evento. Os 25 pares têm dois eventos oficiais diferentes e datas ordenáveis. O campo `event_start` preserva a data e hora; a ordem é revista pelos valores oficiais, com troca consistente dos lados A/B se necessária.

Para a identidade pessoal, o mesmo nome completo é acompanhado por UF de deputado ou por cargo institucional coincidente. Marcadores explícitos de fala ajudam a associar cada manifestação. O caso `Gianna Sagazio` tem marcador `Gianna Cardoso Sagazio`, alias documentado no parser. `Paulo Xavier` permanece `unknown`: os cargos mencionam FEMBRAPP e FANMA, sem identificador pessoal que comprove a equivalência. Nome igual sozinho não confirma pessoa igual. Partido, quando presente, só serve para identidade, nunca para inferir postura.

## Fala, NLI e evidência

`datasetCaio.ipynb` era uma tentativa exploratória de extrair turnos por regex e nomes conhecidos. Essa abordagem pode perder o nome do presidente no formato `PRESIDENTE(Nome)`, além de ser frágil para marcadores não reconhecidos, interrupções e trocas implícitas de orador. O parser em `src/voxlab/provenance.py` exige marcador no início de linha, preserva offsets de caracteres, extrai o nome entre parênteses para presidência e marca turnos com possíveis marcadores internos não analisados. Ele não resolve interrupções sem marcador, citações de terceiros nem todos os formatos possíveis; esses casos exigem revisão. A amostra piloto foi conferida pelos marcadores e trechos originais.

Para cada chunk NLI não vazio dos 41 registros, `pilot_nli_spans.csv` guarda `record_id`, índices de ator/opinião/chunk, método, offsets, texto reconstruído, marcador e turno. `EXACT_MATCH` exige igualdade literal; `NORMALIZED_EXACT_MATCH` só ignora diferenças de espaços e retorna offsets no texto original; `NO_MATCH` não fornece trecho. Não houve fuzzy match. Dos 3.312 chunks, 317 foram exatos, 2.443 exatos após normalização de espaços e 552 não encontrados. Em 2.396 casos houve uma única ocorrência dentro de turno com nome do ator NLI. Isso demonstra localização de trecho, não veracidade do resumo NLI.

`pilot_speech_candidates.csv` oferece até cinco frases literais por lado, classificadas apenas por sobreposição lexical para facilitar revisão. `pilot_evidence_review.csv` registra uma revisão documental dos 50 lados, com offsets, texto selecionado, decisão `true/false/unknown` sobre suporte à manifestação central do resumo LDS e justificativa. A revisão não certifica cada afirmação incidental do resumo. Em cada lado, `speech_verified` exige um turno nomeado e offsets que reconstroem a fala; `evidence_verified` exige ainda trecho literal dentro dessa fala e suporte revisado do resumo. Os offsets são índices de caracteres Python, início inclusivo e fim exclusivo, em `transcricao` original. Uma fala pode estar localizada mesmo quando seu resumo é incorreto. Recomenda-se uma segunda revisão humana independente antes de usar o piloto como gold.

## Funil e perdas

| Etapa cumulativa | Pares |
|---|---:|
| Candidatos | 25 |
| Eventos distintos confirmados | 25 |
| Mesmo ator confirmado | 24 |
| Duas datas de audiência confirmadas | 24 |
| Ordem temporal confirmada | 24 |
| Duas falas localizadas | 24 |
| Duas evidências ligadas ao resumo | 19 |
| Completamente validados | 19 |

As 50 falas foram localizadas, mas `Paulo Xavier` sai do funil na identidade. Entre os 24 restantes, três pares têm relação resumo–evidência incerta (`Augusto Coutinho`, `Danilo Forte`, `Caio Vianna`) e dois têm divergência comprovada (`Gianna Sagazio`, `Vanessa Pirolo`). No caso de Vanessa, a transcrição diz **43 milhões de dólares**, enquanto o resumo LDS afirma **43 bilhões**. No caso de Gianna, a alegação central sobre transportar excesso de recursos para o exercício seguinte não aparece na manifestação localizada. O lado A de Gianna também é incerto quanto à menção específica do PLS 226/16. O resumo de Augusto acrescenta um número de PL ausente na fala selecionada; o de Danilo é mais específico do que a fala; a evidência de Caio não confirma a referência à pesquisa do setor público. Essas incertezas permanecem abertas.

| Motivo (não exclusivo) | Pares | Origem provável |
|---|---:|---|
| Identidade ambígua (`ACTOR_AMBIGUOUS_OR_DIFFERENT`) | 1 | Metadados pessoais insuficientes |
| Ligação resumo–evidência incerta (`SUMMARY_EVIDENCE_LINK_UNCERTAIN`) | 4 | Resumo mais específico que trecho encontrado; inclui Gianna já inválida |
| Divergência resumo–transcrição (`SUMMARY_TRANSCRIPT_MISMATCH`) | 2 | Erro ou extrapolação no resumo LDS |
| Evento/data/fala ausente neste piloto | 0 | Nenhuma perda observada |

Os motivos se sobrepõem. Há 19 `VALIDATED`, 4 `PARTIALLY_VALIDATED` e 2 `INVALID`. `UNKNOWN` não foi convertido em `false` ou `true`. Os 19 pares validados superam o critério de gestão de 15: **GO para iniciar anotação humana de comparabilidade e postura nesses 19 pares de eventos parlamentares**, após segunda revisão documental independente. Se o recorte exigir que **ambos** os eventos sejam classificados oficialmente como audiência pública (incluindo audiência com deliberação), são **14 pares**, correspondentes a **WARNING** pelo mesmo critério. Os cinco restantes incluem comparecimentos de ministro ou seminário; o tipo está no CSV final para filtrar o recorte. A decisão não declara que os pares são semanticamente comparáveis e não generaliza a taxa de 19/25 para o corpus: o piloto foi selecionado por recorrência e similaridade de assunto.

## Reprodução e integridade

Da raiz do repositório, com Python 3.10+ e os três CSVs oficiais presentes:

```bash
PYTHONPATH=src python3 -m voxlab.provenance
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Saídas: `data/processed/provenance_schema.csv`, `pilot_nli_spans.csv`, `pilot_speech_candidates.csv`, `provenance_funnel.json` e `data/annotations/pilot_pairs_validated.csv`. A planilha inicial `pilot_pairs.csv` e a auditoria dos 206 registros permanecem como análise exploratória anterior. Seus `hearing_date` vazios não foram preenchidos retroativamente com os resultados do piloto.
