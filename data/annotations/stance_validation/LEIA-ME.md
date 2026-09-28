# Validação humana de postura: instruções aos anotadores

**Quem faz o quê:**
- Anotador 1: abre só `annotator_1.html` (100 itens).
- Anotador 2: abre só `annotator_2.html` (60 itens).

**Regras:**
- Não abra o arquivo do outro anotador, nem `reference.csv` ou `sample_summary.json`.
- Não converse com o outro anotador sobre os itens até os dois terminarem.

**Como abrir:** dê um duplo clique no arquivo `.html` e ele abre no navegador, sem internet e sem instalar nada. O progresso fica salvo **nesse navegador e nesse computador**. Use sempre o mesmo navegador e exporte o CSV de vez em quando, como backup.

## Cada item
Um item é a fala literal de **um** participante de uma audiência pública da Câmara. Você vê:
- a data da notícia;
- o presidente da época;
- o assunto da audiência;
- 1 a 3 proposições em debate.

Você **não vê** nome, partido nem cargo. Não tente adivinhar quem é: julgue só pelo que está escrito.

**Destaques de leitura:**
- **Amarelo:** menções a governo, ministérios, ministros, presidente, Lula ou Bolsonaro.
- **Azul:** palavras das proposições.
- Parágrafos sem destaque aparecem esmaecidos. **Eles podem conter posição**, então passe os olhos por eles também.
- "Ministro" também marca ministros do STF e de tribunais. O **Judiciário não é governo federal**.

## O que responder
1. **Cada proposição:**
   - **Determinável?** YES se a fala tem posição clara sobre *esta* proposição. NO se não se posiciona (não fala dela, só descreve fatos, só pergunta). UNCERTAIN na dúvida.
   - **Postura (se YES):** FAVOR, AGAINST ou UNCERTAIN, quando a direção não é clara. Não existe "neutro".
2. **Governo federal vigente** (o do presidente indicado: Presidência, ministérios, ações e programas):
   - SUPPORT: elogia ou defende.
   - CRITICIZE: critica, cobra ou se opõe.
   - MIXED: há apoio e crítica explícitos, sem direção predominante.
   - NEUTRAL: menciona só de forma descritiva.
   - NOT_ADDRESSED: não se refere ao governo.
3. **Governos anteriores:** a mesma escala, para governos federais anteriores ao vigente.
4. **Confiança geral:** LOW, MEDIUM ou HIGH. **Notas** são opcionais; use-as nos casos difíceis.

**Regras de decisão:**
- Discurso reportado ("o grupo defende X") e citação sem endosso não são posição do falante.
- Pedido de recursos ou providências sem avaliação conta como NEUTRAL.
- Crítica ao Congresso, ao Judiciário, a estados ou a municípios **não** é posição sobre o governo federal.
- Ironia e pergunta retórica só contam se a direção for inequívoca.

## Ao terminar
Clique em **Exportar CSV** e envie o arquivo `annotator_N_filled.csv`. Não edite o CSV à mão.

Atalhos de teclado: ← e → mudam de item. "Próximo incompleto" pula para o que falta.
