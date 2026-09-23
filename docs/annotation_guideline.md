# Piloto de anotação humana semântica

**Estado atual (2026-09-21):** os dois anotadores entregaram suas planilhas. Preserve-as sem edição. A próxima etapa é a adjudicação descrita em `docs/semantic_agreement.md`; esta guideline documenta a tarefa que eles executaram.

## Unidade, arquivos e independência

Cada linha contém duas manifestações literais do mesmo ator em eventos parlamentares diferentes. O piloto contém **18 pares preliminarmente elegíveis** após duas passagens documentais; a segunda passagem foi feita pelo Codex, **não por uma segunda pessoa humana**. Antes de chamar o resultado de gold, dois humanos devem anotar as manifestações de forma independente e as divergências devem ser adjudicadas. Nenhum resumo LDS, rótulo silver ou julgamento automático é resposta correta por definição.

Anotador 1 abre somente `data/annotations/semantic_pilot_annotator_1.csv`; anotador 2 abre somente `data/annotations/semantic_pilot_annotator_2.csv`. Não abram o arquivo um do outro nem `semantic_pilot_reference.csv` durante a anotação. Cada arquivo tem os mesmos `pair_id`, com ordem de linhas e apresentação A/B aleatórias distintas. **A e B são posições de apresentação, não ordem cronológica**; as datas mostradas são as datas oficiais dos eventos. A correspondência cronológica fica guardada no arquivo de referência. Cada pessoa deve preencher apenas as colunas de resposta listadas abaixo, sem modificar `pair_id`, evento, data, tema, texto, contexto, evidência ou alerta de cegamento.

`event_a/b` usa os códigos `PUBLIC_HEARING`, `MINISTER_APPEARANCE`, `PUBLIC_HEARING_WITH_DELIBERATION`, `SEMINAR` e `OTHER`. O universo inicial inclui os eventos parlamentares presentes no PublicHearingBR; não exclua comparecimentos ou seminários. O tipo permite análise de sensibilidade posterior. `topic_a/b` é o assunto LDS do evento. `text_a/b` é o turno literal completo. `context_before`, `evidence` e `context_after` dividem esse mesmo turno sem alterar caracteres; a concatenação dos três reconstitui `text`. Leia o contexto antes de julgar. A evidência foi verificada documentalmente, mas não implica que haja stance determinável.

Os campos estruturados não incluem nome, partido, UF, cargo ou ID oficial. `blinding_warning` sinaliza possíveis identificadores **dentro** do texto original. Não edite ou substitua palavras da fala para removê-los; anote normalmente, atento ao possível viés. Se a identificação incidental prejudicar a cegueira, registre isso em `annotation_notes_a/b`.

## Cinco conceitos distintos

| Conceito | Pergunta | Exemplo neutro |
|---|---|---|
| Tema | Sobre que assunto geral se fala? | Impostos sobre produto X |
| Proposição | Qual afirmação específica poderia ser aceita ou rejeitada? | O governo deve aumentar o imposto sobre produto X. |
| Stance | O ator favorece ou rejeita sua proposição-alvo? | “Sou favorável ao aumento” → `FAVOR` |
| Comparabilidade | As duas manifestações respondem à mesma proposição específica? | “O governo deve aumentar...” e “Sou favorável ao aumento...” → `YES` |
| Relação temporal | Como se relacionam as stances comparáveis nos dois eventos, respeitando datas? | Derivada depois; nunca anotada diretamente |

“Empresas devem remover conteúdo ilegal” e “Decisões judiciais de remoção devem admitir recurso” pertencem a um tema amplo comum, mas são proposições diferentes: `same_proposition=NO`. Não use semelhança de palavras como substituto do julgamento da proposição. Não pergunte se a pessoa “mudou de opinião”, “se contradisse” ou foi “incoerente”.

## Sequência de preenchimento

1. Para cada lado, responda em `stance_determinable_a/b`: `YES`, `NO` ou `UNCERTAIN` à pergunta: **“A manifestação apresenta uma posição suficientemente clara sobre alguma proposição específica?”** `NO` significa ausência de stance determinável, não neutralidade. Registre `determinability_confidence_a/b` como `LOW`, `MEDIUM` ou `HIGH`.
2. Se o lado recebeu `YES`, escreva em `target_proposition_a/b` uma frase curta, específica e neutra que represente o objeto da posição, sem acrescentar informação ausente. “Regulação de plataformas” é tema amplo; “Plataformas devem remover conteúdo ilegal após notificação” é proposição. Preencha `proposition_confidence_a/b`.
3. Ainda para cada lado com `YES`, preencha `stance_a/b` como `FAVOR`, `AGAINST` ou `UNCERTAIN` **em relação à sua própria proposição-alvo**, e `stance_confidence_a/b`. Se a direção não ficar clara, use `UNCERTAIN`; não crie `NEUTRAL`.
4. Somente quando **ambos** os lados receberam `YES`, responda em `same_proposition`: `YES`, `NO` ou `UNCERTAIN` à pergunta: **“As duas manifestações tratam da mesma proposição ou de proposições semanticamente equivalentes?”** Preencha `comparability_confidence`. `YES` requer comparação direta das posições; mesmo tema, medidas diferentes ou proposições sobrepostas sem equivalência recebem `NO`. Contexto insuficiente recebe `UNCERTAIN`.
5. Use `annotation_notes_a/b` e `comparability_notes` quando houver `UNCERTAIN`, confiança `LOW`, dificuldade especial ou identificação incidental. Uma justificativa curta basta. Os demais campos condicionais ficam vazios quando não se aplicam. Não preencha relação final.

Confiança mede a segurança **daquela decisão**, não a confiança geral no projeto. Para proposições em texto livre, não se calcula Kappa sobre as strings: as formulações serão comparadas manualmente na adjudicação. Preserve sua própria redação.

## Casos especiais

| Caso | Como decidir |
|---|---|
| Negação | Identifique a proposição afirmativa específica e marque `AGAINST` quando a fala a rejeita claramente. Dupla negação exige cuidado. |
| Pergunta retórica | Pode expressar posição se o contexto torna a resposta esperada inequívoca; se houver dúvida, `UNCERTAIN`. |
| Pergunta genuína | Pedido de informação sem endosso ou rejeição normalmente dá `stance_determinable=NO`. |
| Citação de terceiro | Não atribua a frase citada ao ator sem endosso explícito. |
| Discurso reportado | “O grupo defende X” relata posição alheia; procure a avaliação do próprio falante. |
| Ironia | Use contexto e marcas claras; se a direção depender de suposição, `UNCERTAIN`. |
| Hipótese | “Se X ocorrer, Y poderá acontecer” não equivale automaticamente a defender X ou Y. |
| Condicional | Preserve a condição na proposição-alvo quando ela for essencial. |
| Mudança explícita declarada | Anote separadamente a posição expressa em cada manifestação; registre a declaração em nota, sem escolher relação final. |
| Concordância parcial | Formule a parte específica apoiada/rejeitada. Se o lado mistura direções para a mesma proposição, `stance=UNCERTAIN` ou reformule a proposição. |
| Posição implícita | Aceite somente quando o contexto dá uma inferência curta e clara; reduza confiança se necessário. |
| Ausência de posição | Dados descritivos, cumprimentos e explicação de contexto podem receber `NO`. |
| Proposição ampla | Refine até uma afirmação contestável; se não for possível sem inventar conteúdo, `NO` ou `UNCERTAIN`. |
| Proposições sobrepostas | Compartilhar partes, efeito ou tema não basta. Use `same_proposition=NO` se uma posição não responder diretamente à outra. |

## Derivação posterior e concordância

O script `src/voxlab/agreement.py` deriva `INSUFFICIENT_EVIDENCE` quando ao menos um lado tem determinabilidade `NO`; `RELATION_UNCERTAIN` para determinabilidade, comparabilidade ou stance incerta; `INCOMPARABLE` quando ambos têm posição determinável mas `same_proposition=NO`; e `STANCE_MAINTAINED`/`STANCE_REVERSED` somente quando ambos respondem à mesma proposição com stances definidas iguais/opostas. Essa relação não é perguntada aos humanos.

Depois que **ambos** os arquivos estiverem completos, execute `PYTHONPATH=src python3 -m voxlab.agreement`. O script calcula concordância bruta e Kappa separadamente para determinabilidade, comparabilidade, stance e relação derivada, com distribuição de classes e alerta de prevalência. Ele não produz métricas para arquivos vazios ou incompletos. Resultados com amostra pequena e classes raras exigem leitura dos casos individuais; Kappa isolado não decide a viabilidade do estudo.
