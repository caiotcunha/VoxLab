# Estado inicial e auditoria do corpus

## Estado inicial encontrado

**Dados.** `PublicHearingBR_LDS.jsonl` tem 206 objetos com `id`, `materia` (notícia com data/hora de publicação), `metadados.assunto`, `metadados.envolvidos[]` (`nome`, `cargo`, `opinioes[]`) e `transcricao`. São 1.065 entradas de envolvidos e 2.203 opiniões. `PublicHearingBR_NLI.jsonl` tem os mesmos 206 IDs, `metadados_extraidos.assunto`, `tl_dr` e 1.413 entradas de envolvidos, com 4.238 opiniões estruturadas e `chunks_proximos`. Os dois conjuntos de envolvidos divergem, portanto não podem ser fundidos por posição. O CSV tem 5.959 linhas opinião–proposição com IDs dos 206 registros. Todas as linhas casam com uma opinião LDS pelo triplo ID, nome exibido com title case e texto, mas uma opinião pode aparecer em várias proposições.

**Notebooks e pipeline.** `datasetCaio.ipynb` tem 7 células: carrega o LDS, achata atores, normaliza nomes e tenta extrair turnos da transcrição por marcadores, depois divide turnos em chunks. O extrator usa nomes conhecidos, regex de marcador e recorte até o marcador seguinte; é exploratório e pode atribuir fala errada ou perder oradores. `nunes.ipynb` tem 6 células: cria opiniões do LDS, extrai partido de `cargo`, chama `nvidia/nemotron-3-nano-30b-a3b` via LangChain/NVIDIA para 1–3 proposições locais por registro, classifica opinião–proposição como A FAVOR/CONTRA/NEUTRO, grava o CSV e monta um grafo com NetworkX/Pyvis. O HTML inclui dados da rede gerada; não lê o CSV dinamicamente. O texto explicativo do notebook chama o CSV de “Base de Ouro”, mas a origem automática torna essa denominação incorreta. A lógica executável da rede mantém arestas neutras, embora a célula descritiva diga que as filtra.

**Classificação/evidência.** No CSV há 1.583 `A FAVOR`, 247 `CONTRA`, 1.533 `NEUTRO` e 2.596 `ERRO API`. Não há evidência por linha, nem anotação humana. Nenhum dos 2.203 resumos LDS aparece literalmente na transcrição correspondente. No NLI, 1.804 de 16.940 chunks não vazios aparecem literalmente na transcrição; 14.231 aparecem após normalizar espaços. A evidência NLI pode ser investigada posteriormente, mas demanda alinhar ator, opinião e trecho e conferir atribuição. A auditoria atual deixa `evidence` vazia, sem fabricar citação.

**Reúso e problemas.** Foram reutilizados o LDS e o CSV somente como fonte/proveniência e silver; a normalização conservadora de nomes e os assuntos inspiraram o novo loader. Código de chamada à API, grafos e regex de turnos permanece exploratório. Os notebooks antigos dependem de pacotes não documentados em manifesto, trazem lógica científica embutida, e o dashboard HTML gerado está versionado. Datas de publicação não são datas de audiência; nomes normalizados não são IDs pessoais, podendo juntar homônimos e separar aliases. O ID do dataset é tratado como unidade de registro, sem garantia de um evento único. O CSV tem alto volume de falhas de API, e a própria proposição alvo foi gerada por LLM.

**Segurança.** Havia uma chave NVIDIA literal na célula 1 de `nunes.ipynb`; a célula foi alterada para ler somente `NVIDIA_API_KEY` do ambiente. A chave deve ser revogada/rotacionada pelo proprietário e removida do histórico Git se o repositório for compartilhado. Não houve chamada à API nesta auditoria. O HTML carrega bibliotecas de CDN. Saídas salvas do notebook contêm um caminho absoluto de ambiente anterior, sem uso pela nova auditoria.

## Medições da fase 1

Os valores abaixo provêm de `data/processed/audit_summary.json` e do LDS presente nesta cópia. `actor_id` é nome sem acento, pontuação e diferença de caixa; não equivale a identificação humana validada.

| Medida | Resultado | Natureza |
|---|---:|---|
| Registros de origem tratados como unidades de audiência | 206 | Observado, unidade não validada |
| Nomes normalizados distintos | 878 | Derivado |
| Nomes em ≥2 / ≥3 / ≥5 registros | 102 / 47 / 8 | Derivado |
| Distribuição de registros por nome | 1: 776; 2: 55; 3: 30; 4: 9; 5: 5; 6: 2; 16: 1 | Derivado |
| Registros com data de publicação | 206 | Observado |
| Registros com data de audiência verificada | 0 | Observado |
| Pares mesmo nome, IDs diferentes, publicação em dias diferentes | 396 | Derivado |
| Pares com assunto TF-IDF ≥0,10 | 58, em 37 nomes | Heurístico |
| Pares com ordem de audiência verificada | 0 | Observado |

Intervalos **entre publicações** nos 396 pares: 74 até 30 dias, 164 de 31–180, 82 de 181–365 e 76 acima de 365. Entre aparições consecutivas de cada nome, são 62, 93, 21 e 11, respectivamente. A maior recorrência individual foi 16 registros, de maio de 2022 a abril de 2024 em datas de publicação. Apenas um assunto textual idêntico aparece em dois registros com um ator recorrente: “Regulamentação do trabalho de motoristas de aplicativo”. Isso torna essencial uma recuperação temática aproximada, seguida de julgamento humano de proposição.

## Fase 2: seleção temática exploratória

O método tokeniza `metadados.assunto`, calcula TF-IDF local e similaridade cosseno entre os 206 assuntos. Para cada ator, compara IDs distintos com datas de publicação diferentes, aplica limiar ≥0,10 e limita a cinco registros posteriores por registro inicial. A opinião escolhida em cada par maximiza sobreposição de palavras entre os resumos; isso **não** determina stance nem comparabilidade. Todos os 58 pares ficam em `candidate_pairs.csv` com fonte, índices, datas e `temporal_order_verified=false`.

| Limiar | Pares antes do top-k |
|---:|---:|
| 0,05 | 78 |
| 0,10 | 58 |
| 0,15 | 28 |
| 0,20 | 20 |
| 0,30 | 9 |
| 0,40 | 5 |
| 0,50 | 5 |
| 0,60 | 2 |
| 0,70 | 1 |
| 0,80 | 1 |

Os assuntos dos pares de maior similaridade incluem trabalho de motoristas de aplicativo, mercados digitais/PL 2768/22, vacinação infantil contra Covid-19 e substituição do saque-aniversário do FGTS. São possibilidades para estudo de caso, ainda sem validação de proposição ou cronologia.

## Fase 3: piloto e decisão

O piloto contém 25 pares de 25 nomes. Faixas: 9 com similaridade de 0,10–0,15; 8 com 0,15–0,30; 8 com ≥0,30. Intervalos de publicação: 7 até 30 dias, 12 de 31–180, 1 de 181–365 e 5 acima de 365. Há casos potencialmente difíceis e assuntos diversos, sem escolher por `stance_silver`. A planilha cega retira identificação explícita do ator e campos silver, mas requer revisão manual de identificadores incidentais no texto.

**Decisão: WARNING.** Há recorrência nominal e 25 pares para inspeção, mas o corpus fornecido não prova ordem temporal das audiências nem sustenta, ainda, evidência literal atribuída ao ator. A comparabilidade real pode ser muito menor que 58. O próximo trabalho é verificar em fontes primárias a data e a atribuição de cada fala, descartar pares sem suporte e obter dois anotadores humanos independentes. Só após medir a taxa de pares válidos faz sentido implementar e avaliar o gate de comparabilidade.

## Atualização: validação documental do piloto

A decisão acima registra o estado **anterior** à investigação de proveniência. A etapa seguinte associou manualmente os 41 registros do piloto a eventos oficiais, localizou as 50 falas e revisou evidências literais. Resultado: 19 pares `VALIDATED`, 4 `PARTIALLY_VALIDATED` e 2 `INVALID`. Naquele momento, a decisão de gestão foi **GO para preparar anotação humana dos 19 pares de eventos validados**, condicionada à segunda revisão documental. Em recorte estrito de duas audiências públicas, eram 14 pares e a decisão seria **WARNING**. A auditoria dos 206 registros e os 58 candidatos não foram reclassificados. Método, fontes e perdas: `docs/provenance_validation.md`.

## Atualização: piloto semântico humano preparado

Uma segunda passagem documental do Codex conferiu os 38 lados dos 19 pares, preservando a primeira revisão. Houve 37 concordâncias válidas e uma discordância sobre o resumo de Mercedes Bustamante. Restam **18 pares preliminarmente elegíveis**; 13 têm duas audiências públicas. Dois CSVs cegos, com respostas vazias, foram preparados em ordens e apresentações A/B diferentes para duas pessoas anotarem independentemente. A segunda passagem documental **não foi uma segunda pessoa humana**. Não há métricas de concordância, gold humano ou GO para comparability gate. Arquivos, método e instruções: `docs/semantic_pilot.md` e `docs/annotation_guideline.md`.

## Atualização: duas anotações humanas recebidas

Em 2026-09-21, as duas planilhas dos 18 pares foram entregues completas. Após restaurar os lados cronológicos, houve concordância bruta de 34/36 em determinabilidade, 13/16 em mesma proposição, 32/34 em stance e 13/18 na relação derivada. O Kappa de determinabilidade é 0 porque o segundo anotador marcou `YES` nos 36 lados; a concordância bruta de 94,44% deve ser lida com essa prevalência. Cinco pares diferem na relação final derivada. Nenhum anotador produziu `STANCE_REVERSED`. Foi criada uma fila de adjudicação para os 18 pares, sem preencher rótulos gold. Resultados, casos e próximos passos: `docs/semantic_agreement.md`. **Ainda não há GO para comparability gate.**

## Atualização: arquivo de consenso recebido

Em 2026-09-23 foi adicionado e corrigido `semantic_pilot_consensus.csv`. A validação final encontrou 18 pares únicos, respostas completas e correspondência integral com os pacotes de origem. Após restaurar A/B para a ordem cronológica, o consenso resulta em 5 `STANCE_MAINTAINED`, 11 `INCOMPARABLE`, 2 `RELATION_UNCERTAIN` e 0 `STANCE_REVERSED`. Foi gerado `semantic_pilot_gold.csv`, com fonte `HUMAN_CONSENSUS` e hash do consenso. A decisão é GO limitado para estudar o comparability gate, WARNING para avaliação quantitativa com apenas 18 pares e NO-GO para alegar detecção de reversão sem exemplos dessa classe. Veja `docs/semantic_consensus_analysis.md`.

## Atualização: expansão do corpus iniciada

Em 2026-09-23 foi gerada a primeira versão da expansão de candidatos (`src/voxlab/expansion.py`). O universo recalculado confirma 58 candidatos TF-IDF ≥ 0,10; excluídos os 18 pares gold, restam **40 candidatos elegíveis**. Após aplicar cap de 2 pares por ator (Erika Kokay ×6 e outros com recorrência alta foram limitados), a amostra de expansão contém **34 pares de 27 atores**. Todos os 18 pares gold são recuperados pelo retriever TF-IDF ao threshold 0,10. Nenhum label silver ou gold foi usado na seleção. O template inclui IDs e índices da fonte, resumo LDS, metadados oficiais, textos literais e offsets; o validador confere reconstrução, atribuição do turno e cronologia sem sobrescrever respostas humanas. Oito lados presentes em sete pares podem reutilizar proveniência documental já validada. Na geração inicial, os 34 pares estavam `UNRESOLVED` e a decisão era `PROVENANCE_REVIEW_REQUIRED`. Veja `docs/dataset_expansion.md`.

## Atualização: primeira revisão da proveniência expandida recebida

Em 2026-09-24, o arquivo dos 34 pares foi recebido com eventos, datas, marcadores, falas, evidências, offsets e julgamentos de suporte preenchidos. O validador confirmou os 68 lados, os 34 pares de eventos distintos, a ordem temporal e a ausência de lados invertidos. Diferenças de fim de linha nos metadados oficiais e quatro variantes nominais completas nos marcadores foram tratadas como equivalências documentadas. O arquivo humano foi preservado sem alteração.

Os campos `same_actor_verified` e `actor_identity_basis` ficaram vazios nos 34 pares inicialmente. Uma checagem de identidade (nome + cargo/UF), já usada no piloto original mas não conectada no pipeline de expansão, foi religada e estendida com uma regra de cargo idêntico, resolvendo 4 casos automaticamente. Dos 9 pares ainda pendentes, o Gabriel confirmou manualmente a identidade dos 6 casos ambíguos restantes (com justificativa documentada por par) e os 3 pares de evidência pendente (Padre João, Priscila Costa, Vanessa Pirolo) foram marcados `INVALID` em 2026-09-24 após confirmação de divergência factual entre resumo e transcrição literal.

Resultado final: **29 `VALIDATED`, 5 `INVALID`**, 0 pares pendentes, `decision: READY_FOR_EXPANSION_ANNOTATION`. Os pacotes cegos dos dois anotadores foram gerados por `src/voxlab/expansion_semantic_pilot.py`, reaproveitando sem alteração a lógica de cegamento e as seeds do piloto original. Veja `docs/dataset_expansion.md` e `data/processed/expansion_provenance_readiness.csv`.

## Atualização: protocolo e baselines do comparability gate

O piloto foi congelado por hash como conjunto de desenvolvimento, sem divisão artificial em treino e teste. Nos 16 pares com `same_proposition` definido como `YES` ou `NO`, o corte TF-IDF de recuperação 0,10 equivale a sempre prever `COMPARABLE`: 5 verdadeiros positivos e 11 falsos positivos. Os rankings exploratórios obtiveram ROC AUC 0,9091 para assunto, 0,8364 para turno completo e 0,6364 para evidência, sem escolha de limiar. Uma ablação com stance humana e sem gate emitiria 13 relações para pares incomparáveis ou incertos e 2 falsas reversões. Esses números não são avaliação final: o piloto tem 5 positivos, 11 negativos, 2 incertos e participou do desenho do protocolo. Veja `docs/comparability_experiment.md`.

## Atualização: baselines automáticos via LLM (trilha experimental separada)

Em 2026-09-24, dois modelos hospedados na DeepInfra (Qwen2.5-72B-Instruct, Llama-3.3-70B-Instruct-Turbo) foram avaliados nos 18 pares gold em três condições: end-to-end direto, structured com comparabilidade forçada e structured com gate. Ligar o gate transformou 10 erros em acertos em cada modelo, sem piorar nenhum caso no Qwen e piorando 2 no Llama. Esse contraste é parcialmente esperado porque a ablação forçada não pode emitir `INCOMPARABLE`, classe de 11/18 itens. O baseline end-to-end empatou ou superou o pipeline estruturado com gate, portanto a vantagem do pipeline completo ainda não foi demonstrada. Os mesmos métodos, congelados antes dos rótulos humanos da expansão, foram aplicados aos 29 pares como `label_source=MODEL_PREDICTION`. A anotação humana dos 29 continua necessária e as previsões devem permanecer ocultas dos anotadores. Veja `docs/automatic_experiments.md`.

## Atualização: estresse contrafactual e canonização (2026-09-28)

Sem nova anotação humana, os 47 pares do gold foram usados para gerar contrafactuais controlados: reversão, negação na formulação, troca de proposição e reversão em pares incomparáveis. As proposições humanas e dos modelos também foram canonizadas por dois juízes LLM.

- **Resultado central:** o gate automático reduz falsas reversões, mas também elimina as reversões verdadeiras, porque os modelos tratam uma mudança de stance como mudança de proposição.
- **End-to-end:** detecta reversões, mas não reconhece proposições deslocadas.
- **Canonização:** a concordância humana de stance na expansão sobe para κ 0,54. A auditoria de polaridade anterior tinha lados trocados na expansão.

Veja `docs/stress_and_canonicalization.md`.

## Atualização: gate v2 por perguntas neutras (2026-09-28)

Um prompt v2, que julga a comparabilidade apenas por perguntas neutras de sim/não, foi avaliado com dev (piloto), congelamento por hash e teste (expansão). O resultado foi negativo:
- o recall de pares comparáveis sobe;
- a falsa comparabilidade em proposições deslocadas volta;
- as reversões sintéticas do teste continuam não detectadas: no Qwen por leitura de stance, no Llama pelo gate.

Veja `docs/question_gate.md`.

## Atualização: gate desacoplado e modelos maiores (2026-09-28)

Foram avaliados 5 modelos (Qwen2.5, Llama-3.3, GLM-5.2, Nemotron-3-Ultra, gpt-oss-120b) em cinco condições, nos 47 pares do gold e nos 39 contrafactuais. Custo: US$ 2,58.
- **O trade-off se repete em todos os modelos:** o gate reduz falsas reversões e falsa comparabilidade, mas também o recall de reversões.
- **O gate desacoplado remove o vazamento da stance, mas cria um problema de granularidade:** sem alvo compartilhado, as perguntas extraídas separadamente raramente são julgadas equivalentes.

Próximo passo: um contrast set ampliado, com uma condição de alvo compartilhado. Veja `docs/decoupled_gate.md`.

## Próxima fase: gold expandido e avaliação prospectiva

1. Os dois anotadores preenchem independentemente os 29 pacotes cegos, sem acesso a `data/processed/expansion29_model_predictions.csv`.
2. `PYTHONPATH=src python3 -m voxlab.agreement --round expansion` valida completude, vocabulário e integridade dos pacotes, restaura a ordem cronológica e, somente quando ambos estiverem completos, gera concordância, comparação por par, fila de adjudicação e um template de consenso vazio.
3. As discordâncias passam por adjudicação humana em `data/annotations/expansion_semantic_consensus.csv`. Depois do preenchimento, `PYTHONPATH=src python3 -m voxlab.consensus --round expansion` valida as fontes, bloqueia IDs ausentes/duplicados e congela `expansion_semantic_gold.csv` por hash.
4. `PYTHONPATH=src python3 -m voxlab.prospective_evaluation` avalia as previsões já coletadas, sem ajuste de prompt, contra esse novo gold. A comparação principal pré-definida é end-to-end (A) versus structured com gate (C); B permanece uma ablação diagnóstica.
5. A conclusão sobre reversão depende de haver exemplos humanos `STANCE_REVERSED`; se continuarem ausentes, recall dessa classe permanece não estimável e será necessária amostragem dirigida adicional.
