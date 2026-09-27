# Alinhamento partidário e postura em relação ao governo nas audiências

Trilha paralela à linha principal (reversão individual de postura), na branch `party-alignment`. **Ela não depende de nova anotação humana.** A base teórica e as escolhas de desenho estão em `docs/literature_review.md`.

**Estado (2026-09-26):** execução completa.
- 4.364 chamadas à DeepInfra, sem nenhuma falha, com custo real de **US$ 2,88** (`usage.estimated_cost` das respostas).
- Snapshot das votações da Câmara 2022–2024 com hashes em `data/raw/camara_api/SOURCES.json`.
- Resultados em `data/processed/party_alignment_results.json`; figuras em `docs/figures/party_fig*.{pdf,png}`.

Todos os rótulos de postura são `MODEL_PREDICTION`. Não há gold humano para estes alvos.

## Perguntas

- **RQ1:** na mesma audiência e sobre a mesma proposição, deputados do mesmo partido ou bloco concordam mais do que deputados de grupos diferentes?
- **RQ2:** a postura em relação ao governo nas audiências acompanha o governismo dos mesmos deputados nas votações nominais? A concordância entre partidos nas audiências acompanha a co-votação?
- **RQ3:** a postura em relação ao governo federal muda com a alternância Bolsonaro→Lula (1/1/2023)?
- **RQ4:** os resultados são robustos a modelo e a entrada (fala literal × resumo LDS)? O grupo conhecido (Executivo federal) apoia o governo da época?

**Alvo comparável por construção.** A linha principal mostrou que postura só se compara com alvo comum.
- Dentro da audiência, todos são avaliados contra as mesmas 1–3 proposições extraídas da audiência.
- Entre audiências, o alvo é fixo: o governo federal vigente.

## Pipeline

| Etapa | Módulo | Rede | Saída |
|---|---|---|---|
| Tabela ator × audiência, partido do `cargo`, tipo de ator, período, turnos literais | `voxlab.actors` | não | `party_actor_hearings.csv`, `party_actor_summary.json` |
| Proposições centrais por audiência (1 modelo fixo) | `voxlab.hearing_stance --stage propositions` | **DeepInfra** | `party_propositions.csv` |
| Postura por proposição + postura sobre o governo vigente e sobre governos anteriores (2 modelos × 2 entradas) | `voxlab.hearing_stance --stage stance` | **DeepInfra** | `party_stances.csv` |
| Votações nominais, orientação do governo, partido datado | `voxlab.camara_api --download` | **Câmara** | `data/raw/camara_api/` + `SOURCES.json` |
| Análises RQ1–RQ4 | `voxlab.party_alignment` | não | `party_alignment_results.json`, `party_actor_labels.csv` |

- Os comandos com rede são **dry-run por padrão**: mostram o plano e o custo e não enviam nada. Só enviam com `--execute` ou `--download`.
- As respostas brutas ficam em cache em `data/processed/llm_raw_outputs/party_alignment/`, e uma reexecução não repete chamadas.
- O manifesto (`party_manifest_{stage}.json`) registra os hashes dos prompts, os modelos, temperatura 0, a seed e o commit.

**Cegamento.** O prompt de postura não recebe nome, partido, UF nem cargo. Recebe a data, o presidente vigente, o assunto, as proposições e a fala.

**Validação sem anotação:**
- validade convergente com o roll-call (RQ2);
- grupo conhecido: o Executivo federal (RQ4);
- concordância entre modelos e entre entradas (RQ4).

Nada disso é gold.

## Dados locais (sem LLM)

| Medida | Valor |
|---|---:|
| Linhas ator × audiência | 1.065 |
| Com turnos literais localizados | 1.014 (EXACT 759, FIRST_LAST 179, TOKEN_SUBSET 76; 49 sem turno, 2 ambíguos) |
| Deputados federais (linhas) | 357; 349 com partido no `cargo` |
| Executivo federal (linhas) | 79 |
| Audiências com deputados de ≥2 partidos | 64 |
| Audiências Bolsonaro / Lula | 35 / 171 |
| Deputados com fala: Bolsonaro / Lula | 47 / 305 |
| Atores presentes nos dois períodos | 22 |

**Limite de poder da RQ3.**
- No período Bolsonaro há 15 aparições de deputados do PT e **2 do PL**.
- A mudança por partido só é estimável para o PT. O contraste principal agrupa partidos pelo bloco que ocupam no governo Lula (governo, pivô, oposição, derivado do governismo em votações), nos dois períodos.
- O peso do artigo recai sobre RQ1, RQ2 e RQ4 dentro do período Lula (305 aparições de deputados).

**Casamento de nomes.**
- FIRST_LAST e TOKEN_SUBSET só aceitam um único falante candidato na audiência.
- Exemplos conferidos: "Glenn Greenwald" → "GLENN EDWARD GREENWALD"; "Sílvio Almeida" → "MINISTRO SILVIO ALMEIDA".
- Os dois casos ambíguos são variantes do mesmo nome e ficaram sem fala.

## Requisições: plano (dry-run) e execução

| Etapa | Chamadas | Custo estimado |
|---|---:|---:|
| Proposições (Qwen2.5-72B) | 206 | US$ 0,14 |
| Postura, fala literal (Qwen + Llama) | 2 × 1.014 | US$ 2,44 |
| Postura, resumo LDS (Qwen + Llama) | 2 × 1.065 | US$ 0,69 |
| **Total** | **4.364** | **≈ US$ 3,27** (real: **US$ 2,88**) |

- 13 falas passam de 60 mil caracteres e são truncadas, com marcação.
- Câmara: 9 CSVs anuais (votações, votos, orientações 2022–2024) + `deputados.csv`, sem custo.

## Resultados

A condição principal é a **fala literal**, com os dois modelos lado a lado (Qwen2.5-72B / Llama-3.3-70B). A condição de resumo LDS entra como robustez.

### Contexto: votações nominais (Fig. 1)

O governismo em votações confirma a troca de papéis:

| Partido | Governo Bolsonaro | Governo Lula |
|---|---:|---:|
| PT | 0,29 | 0,98 |
| PSOL | 0,21 | 0,81 |
| PL | 0,93 | 0,38 |
| NOVO | 0,68 | 0,24 |
| Centrão (MDB, PSD, PP, Republicanos) | 0,85–0,93 | 0,76–0,81 |
| União | 0,88 | 0,70 |

Classificação em blocos sob Lula:
- **Governo (governismo ≥ 0,70):** PT, PSOL, PCdoB, PSB, PDT, MDB, PSD, PP e Republicanos.
- **Pivô:** União (0,699, na fronteira).
- **Oposição:** PL e Novo.

Casamento com a Câmara: 352 de 357 linhas de deputado; 198 de 201 deputados casados (193 com UF consistente, 5 sem UF no `cargo`).

### RQ2: a fala nas audiências acompanha o voto (Fig. 3)

Correlação de Spearman, por deputado, entre a postura média sobre o governo nas audiências e o governismo em votações no mesmo período:

| Entrada | Período | Qwen | Llama |
|---|---|---:|---:|
| Fala literal | Lula | **ρ = 0,64** (n = 154, p < 0,001) | **ρ = 0,70** (n = 160, p < 0,001) |
| Fala literal | Bolsonaro | ρ = 0,64 (n = 35, p < 0,001) | ρ = 0,62 (n = 37, p < 0,001) |
| Resumo LDS | Lula | ρ = 0,33 (n = 76, p = 0,003) | ρ = 0,39 (n = 91, p < 0,001) |
| Resumo LDS | Bolsonaro | ρ = 0,33 (n = 16, n.s.) | ρ = 0,31 (n = 18, n.s.) |

- **Validade convergente forte com a fala literal**, e quase igual nos dois períodos, mesmo com os partidos trocando de lado.
- Com o resumo jornalístico, a correlação cai à metade e o n cai à metade. Os resumos quase nunca registram a postura sobre o governo: 685–753 dos 1.065 saem `NOT_ADDRESSED`.
- A concordância partido×partido nas audiências contra a co-votação não é interpretável: há poucos pares com n ≥ 3 (n = 35–48; ρ ≈ ±0,1, n.s.).

### RQ3: a alternância inverte a postura sobre o governo (Fig. 2)

Apoio líquido ao governo vigente (+1 apoia, −1 critica; NOT_ADDRESSED excluído), com IC 95% por bootstrap de audiências, agrupado pelo bloco que o partido ocupa sob Lula:

| Bloco (sob Lula) | Bolsonaro, Qwen | Lula, Qwen | Bolsonaro, Llama | Lula, Llama |
|---|---:|---:|---:|---:|
| Governo | −0,53 [−0,76; −0,27] (n = 34) | **+0,42** [0,31; 0,53] (n = 186) | −0,61 [−0,84; −0,35] (n = 36) | **+0,27** [0,18; 0,37] (n = 201) |
| Pivô | −0,75 (n = 4) | −0,17 [−0,48; 0,17] (n = 23) | −1,00 (n = 4) | −0,13 [−0,36; 0,12] (n = 24) |
| Oposição | +0,25 (n = 4) | **−0,62** [−0,80; −0,36] (n = 55) | +0,25 (n = 4) | **−0,71** [−0,86; −0,51] (n = 56) |

**Por partido, Lula, n ≥ 10:**

| Grupo | Qwen | Llama |
|---|---:|---:|
| Executivo federal | +0,88 | +0,78 |
| PT | +0,62 | +0,54 |
| PSOL | +0,50 | +0,13 |
| PSD | +0,38 | +0,13 |
| Sociedade civil | +0,16 | +0,08 |
| Republicanos | +0,06 | +0,10 |
| PP | −0,06 | +0,06 |
| União | −0,25 | −0,12 |
| PL | −0,61 | −0,72 |

**Leituras:**
- **PT de −0,93 / −1,00 (Bolsonaro, n = 15) para +0,62 / +0,54 (Lula).**
- **O centrão classificado como "governo" pelo voto (PSD, PP, Republicanos) fica perto de zero na fala.** O voto governista não vem acompanhado de apoio discursivo. Isso é coerente com Zucco (2009): governismo sem ideologia.
- **Sob Lula, o governo anterior é criticado de forma quase unânime:** PT −0,97 / −0,94; PSOL −1,00; Executivo −0,90 / −0,86; sociedade civil −0,83 / −0,86.
- **O PL, sob Lula, fica dividido em relação ao governo anterior:** +0,06 no Qwen e +0,50 no Llama.
- **Atores presentes nos dois períodos:** 20 (Qwen). Exemplos:
  - Erika Kokay: −1,00 (n = 5) → +0,44 (n = 11)
  - Rogério Correia: −1,00 → +1,00
  - Bia Kicis: +1,00 → −0,75
  - Paulo Teixeira: −1,00 → +1,00

  É a "reversão com alvo comparável garantido" que a linha principal não conseguiu observar.
- **A sociedade civil também se desloca:** −0,44 → +0,16 / −0,43 → +0,08. Isso é compatível com viés de convite: as comissões convidam quem as maiorias preferem.
- **Limite:** antes de 2023 há apenas 4 deputados de oposição e 4 de pivô sob Lula. O contraste robusto é o do bloco que virou governo.

### RQ1: nas proposições da audiência, partido pesa pouco (Fig. 4)

Concordância entre pares de deputados que tomaram posição sobre a mesma proposição na mesma audiência:

| Entrada, modelo | Mesmo partido | Partidos diferentes | p (permutação) | Mesmo bloco | Blocos diferentes | p |
|---|---:|---:|---:|---:|---:|---:|
| Fala, Qwen | 0,93 (69) | 0,83 (236) | 0,079 | 0,91 (160) | 0,79 (145) | **0,012** |
| Fala, Llama | 0,84 (83) | 0,78 (356) | 0,536 | 0,80 (227) | 0,77 (212) | 0,504 |
| Resumo, Qwen | 1,00 (9) | 0,86 (43) | 0,403 | 0,96 (27) | 0,80 (25) | 0,642 |
| Resumo, Llama | 0,91 (23) | 0,85 (84) | 0,194 | 0,92 (49) | 0,81 (58) | 0,277 |

- **A concordância é alta em qualquer par (0,77–0,93):** as proposições das audiências são majoritariamente consensuais. A distribuição de posturas é dominada por FAVOR: 1.658–1.730 FAVOR contra 257–341 AGAINST na fala.
- **O efeito de grupo é pequeno (+0,03 a +0,13)** e só significativo num modelo. Também é sensível ao corte de bloco: com 0,35/0,65, p = 0,30; com 0,45/0,75, p = 0,017.
- **Contraste com a RQ3:** nas audiências, **a divisão partidária aparece na avaliação do governo, não nas proposições de política pública em pauta**.

### RQ4: robustez da medição

- **Concordância entre modelos:**
  - postura sobre o governo: κ = 0,61 (fala), 0,63 (resumo);
  - postura por proposição: κ = 0,55 nas duas entradas.
- **Concordância entre entradas (fala × resumo), no mesmo modelo:** κ = 0,16 (governo) e 0,28–0,35 (proposições). Resumo e fala medem coisas diferentes, e a validade externa favorece a fala (RQ2).
- **Grupo conhecido:** o Executivo federal sob Lula tem apoio líquido de +0,88 / +0,78 (58 de 66 e 53 de 67 SUPPORT). Sob Bolsonaro há só 8 casos (+0,63 / +0,13), e o Llama marca a maioria como NEUTRAL.
- **Saídas malformadas:** 99 de 4.158 chamadas (2,4%). Quase sempre é um valor inválido de `stance_determinable` em uma proposição; o campo é anulado e o resto é mantido.

### Auditoria das proposições (amostra de 22 audiências)

- A maioria são proposições de política contestáveis.
- Uma minoria é factual ou descritiva, como "O setor mineral mata quase três vezes mais…", ou redundante (P1 e P2 como quase-negações). O prompt não foi alterado depois de observar isso.
- 206 audiências com proposições: 201 com 3, 3 com 2 e 2 com 1; 0 malformadas.

## Ameaças à validade

1. **Sem gold humano.** A validade vem do roll-call (externo, comportamental), do grupo conhecido e da concordância entre modelos, não de anotação.
2. **Vazamento pelo texto:** o cegamento remove nome, partido e cargo, mas a própria fala pode revelar filiação ("nosso governo"). Isso faz parte do conteúdo político medido, mas pode inflar a RQ2.
3. **Seleção:** audiências noticiadas pela Agência Câmara; convidados escolhidos por requerimento.
4. **Desbalanceamento temporal:** 35 audiências pré-2023 contra 171 depois.
5. **Data:** usamos a data de publicação da notícia, não a da audiência. Nenhuma audiência fica perto da virada de 2023.
6. **Proposições geradas por um único modelo (Qwen)** a partir da notícia. Proposições consensuais reduzem o poder da RQ1.
7. **Governismo:** votos Sim/Não contra a orientação Sim/Não do governo (1.098 votações). "Obstrução" e "Liberado" são excluídos.

## Decisões declaradas

- **Bloco pelo governismo:** a média partidária de voto conforme a orientação do governo define oposição < 0,40 ≤ pivô < 0,70 ≤ governo. A sensibilidade é reportada com 0,35/0,65 e 0,45/0,75.
- **Escala de apoio líquido:** SUPPORT = +1, CRITICIZE = −1, MIXED/NEUTRAL = 0. NOT_ADDRESSED é excluído. Os IC são por bootstrap de audiências.
- **Partido:** o partido datado vem do registro de votos do deputado. Sem casamento com a Câmara, usa-se o partido do `cargo`, marcado em `party_source`.

## Dashboard

`site/index.html` é um site estático gerado por `voxlab.site_data`, com os dados embutidos em `site/data.js` (~2,6 MB). Abas:
- visão geral (versões interativas das figuras);
- audiências (proposições e postura de cada participante, com as divergências entre modelos destacadas);
- deputados (partido, governismo e linha do tempo da postura sobre o governo);
- partidos e grupos;
- metodologia.

Funciona por `file://` e está pronto para GitHub Pages, mas ainda não foi publicado.

## Reprodução

```bash
conda activate voxlab
PYTHONPATH=src python -m voxlab.actors
PYTHONPATH=src python -m voxlab.hearing_stance --stage propositions            # dry-run
PYTHONPATH=src python -m voxlab.hearing_stance --stage propositions --execute  # requer aprovação e DEEPINFRA_API_KEY
PYTHONPATH=src python -m voxlab.hearing_stance --stage stance --execute
PYTHONPATH=src python -m voxlab.camara_api --download
PYTHONPATH=src python -m voxlab.party_alignment
PYTHONPATH=src python -m voxlab.party_figures
PYTHONPATH=src python -m voxlab.site_data
PYTHONPATH=src python -m unittest discover -s tests -v
```
