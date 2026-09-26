# Revisão de literatura: postura de atores, partidos e dinâmica governo–oposição em audiências públicas

Base teórica da trilha `party-alignment` (branch homônima). O objetivo é situar quatro perguntas:
- **RQ1:** alinhamento partidário dentro da audiência.
- **RQ2:** rede de atores e pontos ideais.
- **RQ3:** evolução temporal na troca de governo de 2023.
- **RQ4:** robustez da medição por LLM.

Cada item registra a referência, o que ela afirma e **o que ela sustenta ou restringe no nosso desenho**.

**Status de verificação.**
- `[V]`: metadados conferidos em página do editor, arXiv ou ACL Anthology nesta revisão.
- `[P]`: referência conhecida, mas ainda sem conferência de volume, páginas ou DOI. Conferir antes de citar no artigo.

---

## 1. O corpus: PublicHearingBR

- **Fernandes, L. C.; Dobins, G. Z. R.; Lotufo, R.; Pereira, J. A. (2024).** *PublicHearingBR: A Brazilian Portuguese Dataset of Public Hearing Transcripts for Summarization of Long Documents.* arXiv:2410.07495. Dataset: `unicamp-dl/PublicHearingBR` (Hugging Face). `[V]`
  - Transcrições de audiências públicas da Câmara pareadas com notícias da Agência Câmara e resumos estruturados (atores, cargos, opiniões). Os resumos saem das **notícias** via LLM.
  - O arquivo NLI (4.238 opiniões) traz `verificacao_manual`, a verificação humana de que a opinião é inferível dos trechos próximos (sinal de alucinação), e julgamentos automáticos de vários LLMs.
  - **Para nós:** o corpus foi desenhado para sumarização, não para análise política, e nenhum trabalho encontrado o usa para postura ou partido. Há duas consequências:
    1. Uma opinião do LDS é um **resumo jornalístico mediado por LLM**, não fala. Por isso o plano prioriza os turnos literais (`provenance.parse_turns`) e trata o resumo como condição de sensibilidade (RQ4).
    2. A seleção das audiências é a da cobertura da Agência Câmara. Isso é viés de seleção a declarar.

## 2. Detecção de postura (stance)

- **Mohammad, S. et al. (2016).** SemEval-2016 Task 6: Detecting Stance in Tweets. *Proc. SemEval*, ACL Anthology S16-1003. `[V]`
  - Define postura como favor/contra/nenhum em relação a um **alvo** explícito. A tarefa B (alvo sem treino) é o antecedente do cenário zero-shot.
  - **Para nós:** justifica a definição de postura *em relação a um alvo* e o uso de alvos distintos: proposição da audiência (RQ1–2) e governo federal (RQ3).
- **Küçük, D.; Can, F. (2020).** Stance Detection: A Survey. *ACM Computing Surveys* 53(1). doi:10.1145/3369026. `[V]`
- **ALDayel, A.; Magdy, W. (2021).** Stance detection on social media: State of the art and trends. *Information Processing & Management* 58(4):102597. `[V]`
  - Consolidam taxonomias. A postura é diferente de sentimento e depende do alvo; também incluem sinais de rede.
  - **Para nós:** sustentam não usar sentimento como proxy de postura. Isso diferencia o nosso desenho de Izumi & Medeiros (2021; §5), que usam sentimento.
- **Abercrombie, G.; Batista-Navarro, R. (2020; 2022).** ParlVote (LREC 2020) e *Policy-focused Stance Detection in Parliamentary Debate Speeches*, NEJLT 2022 (ACL Anthology 2022.nejlt-1.5). `[V]`
  - Postura em debates do Parlamento britânico, rotulada pelo **voto** do orador na moção debatida. É a ideia de usar o voto como supervisão ou validação.
  - Mostram que a postura em debate parlamentar é orientada a **propostas de política** (policy preferences).
  - **Para nós:** é o precedente direto para validar postura extraída de fala com votação nominal (RQ2) e para o alvo ser uma proposição de política (RQ1).
- **Pavan, M. C.; Paraboni, I. et al.**
  - *UstanceBR: a social media language resource for stance prediction*, Language Resources and Evaluation (2025/2026), arXiv:2312.06374. `[V]`
  - *A benchmark for Portuguese zero-shot stance detection*, Journal of the Brazilian Computer Society (JBCS 3932). `[V]`
  - São recursos de postura em PT-BR, com alvos polarizados (incluindo os dois presidentes, Lula e Bolsonaro), mas no domínio Twitter/X. O benchmark zero-shot em português mostra desempenho competitivo sem supervisão.
  - **Para nós:** são a referência para postura em português. **Nenhum cobre fala institucional/legislativa.** Nossa contribuição de domínio está aí.
- **Zero-shot com LLM:** Zhang et al., *Investigating Chain-of-thought with ChatGPT for Stance Detection on Social Media* (arXiv:2304.03087) `[V]`; *Can Large Language Models Address Open-Target Stance Detection?* (arXiv:2409.00222) `[V]`.
  - LLMs são competitivos em stance zero-shot, mas sensíveis a prompt.
  - O caso de **alvo aberto** (o modelo gera o alvo) é mais difícil que o de alvo dado.
  - **Para nós:** justifica separar em duas etapas congeladas (extrair proposições da audiência, depois classificar a postura com alvo dado) em vez de uma etapa única de alvo aberto. É coerente com o comparability gate da linha principal.

## 3. Escalonamento ideológico a partir de texto e validação

- **Laver, M.; Benoit, K.; Garry, J. (2003).** Extracting Policy Positions from Political Texts Using Words as Data. *APSR* 97(2). `[P]` (Wordscores, supervisionado por textos de referência).
- **Slapin, J. B.; Proksch, S.-O. (2008).** A Scaling Model for Estimating Time-Series Party Positions from Texts. *AJPS* 52(3):705–722. `[V]` (Wordfish, não supervisionado, Poisson).
- **Vafa, K.; Naidu, S.; Blei, D. (2020).** Text-Based Ideal Points. *ACL 2020*. `[P]` (TBIP).
- **Rheault, L.; Cochrane, C. (2020).** Word Embeddings for the Analysis of Ideological Placement in Parliamentary Corpora. *Political Analysis* 28(1):112–133. `[V]`
  - "Party embeddings" validados contra o Manifesto Project, especialistas **e roll-call**.
- **Wu, P. Y.; Nagler, J.; Tucker, J. A.; Messing, S. (2023).** Large Language Models Can Be Used to Estimate the Latent Positions of Politicians. arXiv:2303.12057. `[V]`
  - Comparações pareadas por LLM escaladas com Bradley–Terry. Correlação alta com DW-NOMINATE.
- **Le Mens, G.; Gallego, A.** Positioning Political Texts with Large Language Models by Asking and Averaging. *Political Analysis* (2025); arXiv:2311.16639. `[V]`
- **O'Hagan, S.; Schein, A.** Measurement in the Age of LLMs: An Application to Ideological Scaling. arXiv:2312.09203. `[V]`
- **Burnham, M.** Semantic Scaling: Bayesian Ideal Point Estimates with Large Language Models. arXiv:2405.02472. `[V]`
- **O padrão da área:** um escalonamento textual só ganha validade quando é comparado a um critério externo. O critério costuma ser roll-call (NOMINATE), survey de elites ou expert survey.
- **Para nós:**
  1. Nossa RQ2 segue exatamente esse padrão, com o critério externo das votações nominais da Câmara.
  2. Em vez de escalonar palavras, escalonamos **posturas explícitas sobre proposições comuns**. Isso aproxima a matriz ator×proposição de uma matriz de votos. É o argumento para usar métodos de ideal point sobre essa matriz, como SVD ou IRT, e não Wordfish.
  3. Wordfish e TBIP sobre os mesmos turnos são **baselines** naturais para a RQ2.

## 4. Pontos ideais, coalizão e governismo no Brasil

- **Figueiredo, A. C.; Limongi, F. (1999).** *Executivo e Legislativo na nova ordem constitucional.* FGV. `[P]`
  - Também "Bases institucionais do presidencialismo de coalizão", *Lua Nova* (1998) `[V]`.
  - Alta disciplina partidária na Câmara; o comportamento em plenário é previsível pela orientação do líder e do governo.
- **Abranches, S. (1988).** Presidencialismo de coalizão: o dilema institucional brasileiro. *Dados* 31(1). `[P]`
- **Zucco, C. (2009).** Ideology or What? Legislative Behavior in Multiparty Presidential Settings. *Journal of Politics* 71(3):1076–1092. `[V]`
  - O voto em plenário no Brasil se desvia da ideologia de formas que indicam influência presidencial (pork, cargos). A dimensão dominante do roll-call é **governo–oposição**, não esquerda–direita.
- **Zucco, C.; Lauderdale, B. (2011).** Distinguishing Between Influences on Brazilian Legislative Behavior. *Legislative Studies Quarterly* 36(3). Dados: Harvard Dataverse hdl:1902.1/15572. `[V]` (dataset) / `[P]` (páginas)
  - Combina roll-call e surveys (Brazilian Legislative Surveys) para separar ideologia de efeito governo–oposição.
- **Power, T. J.; Zucco, C.** Elite Preferences in a Consolidating Democracy: The Brazilian Legislative Surveys, 1990–2009. *LAPS* `[V]`.
  - Também Zucco & Power, *The Ideology of Brazilian Parties and Presidents: Coalitional Presidentialism Under Stress*, *LAPS* (2023/2024) `[V]`: posições partidárias recentes, inclusive pós-2019.
- **Desposato, S. W. (2006).** Parties for Rent? Ambition, Ideology, and Party Switching in Brazil's Chamber of Deputies. *AJPS* 50(1):62–80. `[V]`
- **Redes de votação na Câmara:** *Evaluating Presidential Support in the Brazilian House of Representatives Through a Network-Based Approach* (arXiv:2109.03638) `[V]`; *Brazilian Congress structural balance analysis* (arXiv:1609.00767) `[V]`; *Complex networks applied to political analysis: group voting behavior in the Brazilian congress*, PLOS One (2025) `[V]`.
  - Redes assinadas de co-votação, detecção de comunidades e balanço estrutural.
- **Para nós (a principal correção ao plano):**
  1. A literatura brasileira prevê que o **eixo governo–oposição** domina o comportamento e pode dominar o **discurso**. Então a RQ1 deve testar os dois agrupamentos em paralelo: partido/ideologia (esquerda–direita, via Zucco & Power) e bloco governo/oposição (por período). Perguntamos qual explica mais a concordância nas audiências.
  2. A RQ2 deve usar como critério a **taxa de governismo** (voto conforme a orientação do líder do governo), e não só um ponto ideal 1D genérico.
  3. As redes de co-votação da literatura dão o formato de comparação para a nossa rede assinada de co-postura.
  4. A troca de partido (Desposato) é comum. O partido deve ser **datado** (partido na data da audiência), não fixo.

## 5. Fala parlamentar, disciplina e o que o discurso revela

- **Proksch, S.-O.; Slapin, J. B. (2015).** *The Politics of Parliamentary Debate: Parties, Rebels and Representation.* Cambridge UP. `[V]`
  - Partidos controlam quem fala e o que se fala. Em sistemas com voto centrado no candidato, há mais espaço para dissenso na fala do que no voto.
  - **Para nós:** o Brasil tem lista aberta (voto personalizado), o que prevê **mais dissenso na fala que no voto**. Isso dá uma hipótese direcional para a RQ2: a correlação fala↔voto será positiva, mas imperfeita, e o desvio é informativo, não só ruído. Também torna publicável um resultado de baixa correlação.
- **Izumi, M. Y.; Medeiros, D. B. (2021).** Government and Opposition in Legislative Speechmaking: Using Text-As-Data to Estimate Brazilian Political Parties' Policy Positions. *Latin American Politics and Society* 63(1):145–164. `[V]`
  - Usa análise de sentimento em cerca de 64 mil discursos de senadores. A dimensão governo–oposição do voto **também aparece no discurso**; presidente e líderes influenciam como parlamentares falam.
  - **Para nós:** é o **trabalho mais próximo**. Diferenças:
    1. Câmara/audiências de comissão, não plenário do Senado.
    2. Postura por alvo, não sentimento.
    3. O período cruza a alternância de 2023, que permite um contraste dentro dos mesmos atores.
    4. Inclui atores não parlamentares (sociedade civil, Executivo) na mesma rede.
- **Moreira, D. et al.** Com a Palavra os Nobres Deputados: Ênfase Temática dos Discursos dos Parlamentares Brasileiros. *Dados* `[V]` (ano e volume `[P]`)
  - Modelo de agenda expressa (Grimmer) em discursos da Câmara. É o antecedente de texto-como-dado na Câmara.
- **Estudos de alternância e retórica (Reino Unido):** MPs que passam da oposição ao governo reduzem perguntas condenatórias, e vice-versa (*Asking Too Much? The Rhetorical Role of Questions in Political Discourse*, arXiv:1708.02254). `[V]`
  - **Para nós:** é o mecanismo esperado da RQ3 (efeito de papel, não de ideologia), com desenho análogo: os mesmos indivíduos antes e depois da alternância.

## 6. Audiências públicas e comissões

- **Barros, A. T. et al.** Audiências públicas interativas na Câmara dos Deputados: além da função informacional. *Revista Brasileira de Ciência Política* (RBCP). `[V]` (autoria completa e ano `[P]`)
- **Representação de interesses na Câmara dos Deputados: estratégias, atores e agenda política**, RBCP `[V]`; **Redes de interesses organizados no sistema comissional da Câmara dos Deputados**, *Revista de Sociologia e Política* `[V]`.
  - A participação em audiência **depende de convite** (requerimento de parlamentar aprovado pela comissão), e audiências são arena de lobby e grupos de interesse.
- **"Partidos e Comissões no Presidencialismo de Coalizão"**, *Dados* `[V]`: controle partidário das comissões.
- **Audiências no Congresso dos EUA:** CoCoHD (arXiv:2410.03099) e C-QUERI (arXiv:2509.21548) `[V]`.
  - O partido de quem pergunta é previsível pelo texto de forma modesta (≈59%, variando muito por comissão e por governo unificado ou dividido). Comitês tendem a convidar testemunhas alinhadas às preferências da maioria.
- **Para nós:**
  1. **Viés de convite:** convidados da sociedade civil provavelmente se alinham a quem os convidou. Isso é ameaça e também oportunidade. Se o requerimento de convite for recuperável pela API da Câmara, "quem convidou quem" vira uma aresta observada da rede (extensão futura).
  2. A literatura dos EUA sugere que a partidarização varia por comissão e por tema. A RQ1 deve incluir efeito de comissão/tema, não só de partido.
  3. Não encontramos estudo computacional de **postura** em audiências públicas brasileiras.

## 7. Polarização brasileira 2022–2023

- **Samuels, D. J.; Belarmino, K. (2025).** Partisan Dehumanization in Brazil's Asymmetrically Polarized Party System. *Journal of Politics in Latin America*. `[V]`
- **Dynamics of sociopolitical polarization … around the 2022 Brazilian elections.** *Nature Communications* (2026). `[V]`
  - Polarização afetiva lulistas×bolsonaristas intensa antes da eleição e atenuada depois. A polarização é **assimétrica**.
- **Para nós:** a RQ3 deve medir **assimetria**. A mudança de postura em relação ao governo pode ser maior de um lado (novos opositores: PL/Novo) do que do outro (novos governistas: PT/PSOL). O centrão (PSD, PP, União, Republicanos) aderiu parcialmente ao governo Lula em 2023 e é o grupo de maior interesse teórico (governismo sem ideologia; Zucco 2009).

## 8. LLMs como instrumento de medição

- **Gilardi, F.; Alizadeh, M.; Kubli, M. (2023).** ChatGPT outperforms crowd workers for text-annotation tasks. *PNAS* 120(30). doi:10.1073/pnas.2305016120. `[V]`
- **Törnberg, P. (2025).** Large Language Models Outperform Expert Coders and Supervised Classifiers at Annotating Political Social Media Messages. *Social Science Computer Review*. doi:10.1177/08944393241286471. `[V]`
  - Também Törnberg, *Best Practices for Text Annotation with Large Language Models*, *Sociologica* `[V]`.
- **Ziems, C. et al. (2024).** Can Large Language Models Transform Computational Social Science? *Computational Linguistics* 50(1):237–291. `[V]`
  - Em rotulagem taxonômica, LLMs zero-shot não batem modelos ajustados, mas chegam a concordância razoável com humanos.
- **Pangakis, N.; Wolken, S.; Fasching, N. (2023).** Automated Annotation with Generative AI Requires Validation. arXiv:2306.00176. `[V]`
  - O desempenho varia por tarefa e por dataset, e a validação tem de ser feita tarefa a tarefa.
- **Barrie, C. et al.** To Err Is Human; To Annotate, SILICON? Toward Robust Reproducibility in LLM Annotation. arXiv:2412.14461. `[V]`
  - Reprodutibilidade: versões de modelo, prompts, parâmetros e depreciação de modelos fechados.
- **Pires, R. et al. (2023).** Sabiá: Portuguese Large Language Models. arXiv:2304.07880 (BRACIS 2023). `[V]`
  - O pré-treino monolíngue melhora tarefas com conhecimento cultural brasileiro.
- **Para nós:** o nosso desenho responde diretamente a Pangakis e Barrie:
  1. Pesos abertos (Qwen, Llama), versionados, temperatura 0, seed, prompts congelados com hash, cache de respostas brutas.
  2. **Validação sem nova anotação** por três vias: (a) gold humano de postura por lado já existente (18 pares, 36 lados) para a stance por lado; (b) validade convergente com roll-call; (c) validade de "grupo conhecido": ministros do Executivo em 2023 devem apoiar o governo.
  3. Em vez de tratar o LLM como gold, reportamos a concordância entre modelos.
  4. Um modelo PT-nativo (Sabiá-3, via Maritaca) seria uma terceira condição desejável, mas custa API fora da DeepInfra. Fica como opcional.

---

## 9. Lacuna e posicionamento

**Lacuna.** Não encontramos trabalho que:
1. meça **postura por alvo** (não sentimento, não tópico) de atores em **audiências públicas de comissão** no Brasil;
2. valide essa medida contra **comportamento de voto nominal** dos mesmos deputados;
3. explore a **alternância de governo de 2023** como contraste dentro dos mesmos atores;
4. junte parlamentares e **atores não parlamentares** (sociedade civil, Executivo) numa mesma rede de postura.

O trabalho mais próximo (Izumi & Medeiros 2021) usa sentimento em plenário do Senado, antes do período, e só com parlamentares. O PublicHearingBR nunca foi usado para análise política.

**Contribuições propostas:**
1. **Recurso/método:** pipeline reprodutível de postura por alvo em transcrições longas de audiências, com fala literal atribuída ao ator e duas camadas de alvo comparável por construção. Liga-se ao achado da linha principal: sem alvo comum, a comparação de postura gera relações indevidas.
2. **Substantiva:** quanto partido e bloco governo/oposição estruturam o que se diz em audiências, se isso muda com a alternância e de modo assimétrico, e como a fala se relaciona com o voto.
3. **Metodológica:** validação de medição por LLM sem nova anotação, via critério externo (roll-call) e grupos conhecidos, seguindo Pangakis e Barrie.

**Ajustes ao plano derivados da literatura:**

| Ajuste | Fonte | Mudança |
|---|---|---|
| Testar dois agrupamentos em paralelo | Zucco 2009; Zucco & Lauderdale 2011 | RQ1 compara partido/ideologia vs. bloco governo–oposição datado |
| Critério principal da RQ2 = governismo | Figueiredo & Limongi; Zucco | Taxa de voto conforme a orientação do governo, por deputado e período, além do ponto ideal 1D |
| Hipótese direcional fala ≠ voto | Proksch & Slapin 2015 | Correlação positiva, mas imperfeita, esperada; a divergência é analisada |
| Assimetria na RQ3 | Samuels & Belarmino; polarização assimétrica | Medir a mudança separadamente para novos governistas, novos opositores e centrão |
| Partido datado | Desposato 2006 | Partido na data da audiência, via histórico da API |
| Efeito de comissão/tema | CoCoHD/C-QUERI | Efeito fixo de comissão/tema na RQ1 |
| Viés de convite | literatura de audiências e lobby | Declarar como ameaça; opcional: coletar requerimentos de convite |
| Baselines de escalonamento | Wordfish, TBIP, Rheault & Cochrane | Wordfish sobre os mesmos turnos como baseline na RQ2 |
| Postura ≠ sentimento | Küçük & Can; ALDayel & Magdy | Não usar sentimento como proxy; reportar a diferença para Izumi & Medeiros |

**Fonte de roll-call confirmada:** arquivos em lote da Câmara (`dadosabertos.camara.leg.br/arquivos/votacoes*/…-{ano}.csv`, incluindo votos por deputado e orientações de bancada/governo). A API REST não expõe votos por deputado diretamente; por isso usaremos o download em lote de 2022–2024, pedindo autorização antes.

## Referências a conferir antes da redação
Wordscores (APSR 2003), TBIP (ACL 2020), Abranches (1988), Figueiredo & Limongi (1999), Zucco & Lauderdale (LSQ 2011, páginas), autoria e ano do artigo da RBCP sobre audiências interativas, *Com a Palavra os Nobres Deputados* (ano/volume).
