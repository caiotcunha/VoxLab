# Protocolo do contrast set v2 (registrado antes da execução)

Escrito e commitado em 2026-09-28, antes de qualquer chamada desta rodada. Qualquer desvio posterior deve ser registrado no documento de resultados como desvio.

## Objetivo e hipóteses

**Objetivo.** Medir, com n maior e controles de qualidade definidos antes da rodada, o trade-off do comparability gate observado nos 39 contrafactuais da v1 (`docs/decoupled_gate.md`).

**Hipóteses:**
- **H1 (trade-off).** Em todos os modelos, as condições com gate (C, D, E) têm menos falsas reversões e menos falsa comparabilidade do que as condições sem gate (B e D-forçado), e também menor recall de reversões.
- **H2 (alvo compartilhado).** A condição E, alvo ancorado, tem maior recall de itens comparáveis do que D, gate desacoplado, sem aumentar a falsa comparabilidade em mais de 10 pontos percentuais.
- **H3 (tipologia).** A falsa comparabilidade varia com o tipo de fronteira deslocada (instrumento, população, objeto, escopo). É uma hipótese exploratória, sem direção prevista.
- **H4 (modelo).** A variação entre condições é maior do que a variação entre modelos dentro de uma condição. É descritiva; será mostrada na figura do trade-off.

## Itens

**Fonte:** os 47 pares do gold humano (18 do piloto e 29 da expansão). Só entram lados com stance determinada e proposição-alvo preenchida no gold.

| Operação | Pares de origem | Lados reescritos | Variantes | Relação esperada |
|---|---|---|---|---|
| `REVERSE` | `STANCE_MAINTAINED` | b, a, b | 3 (estilos distintos) | `STANCE_REVERSED` |
| `NEGATED_PARAPHRASE` | `STANCE_MAINTAINED` | a, b | 2 por lado | `STANCE_MAINTAINED` |
| `SHIFT_INSTRUMENT`, `SHIFT_POPULATION`, `SHIFT_OBJECT`, `SHIFT_SCOPE` | `STANCE_MAINTAINED` | a, b | 1 por lado e tipo | `INCOMPARABLE` |
| `REVERSE_ON_INCOMPARABLE` | `INCOMPARABLE` | a, b | 1 por lado | `INCOMPARABLE` |
| `ALIGN_MAINTAIN` | `INCOMPARABLE` | b | 1 | `STANCE_MAINTAINED` |
| `ALIGN_REVERSE` | `INCOMPARABLE` | b | 1 | `STANCE_REVERSED` |

Em `ALIGN_*`, o lado b é reescrito para tomar posição sobre a proposição-alvo do lado a, com a mesma stance de a (`MAINTAIN`) ou a oposta (`REVERSE`). O rótulo esperado é consequência da operação aplicada a um par com rótulo humano, e fica registrado como `SYNTHETIC_EXPECTED`.

## Geração

- **Modelo:** DeepSeek-V3.1, temperatura 0, prompt `prompts/contrast_generate_v1.txt`.
- **Variação entre variantes:** vem de uma instrução de estilo por variante, não de amostragem aleatória.
- **Explicitude:** o gerador é instruído a não copiar a formulação da proposição-alvo e a manter o nível de explicitude da fala original.

## Aceitação (todos os critérios são obrigatórios)

**Checagens determinísticas:**
1. saída no formato pedido, com texto não vazio;
2. razão de comprimento entre 0,6 e 1,5;
3. similaridade de palavras com o original ≥ 0,40;
4. pelo menos um parágrafo alterado substantivamente (similaridade de caracteres < 0,985);
5. no máximo 1 substituição de palavra com cara de erro de digitação: troca de uma palavra por outra com similaridade de caracteres ≥ 0,85 e mesma letra inicial;
6. **explicitude:** a quantidade de palavras de conteúdo da proposição-alvo presentes no texto reescrito não pode passar de max(original + 2, referência + 2). A referência é o outro lado do par quando ele trata da mesma proposição (operações `ALIGN_*`); nas demais, o próprio texto original.

**Dois verificadores independentes,** Qwen3-235B-A22B-Instruct-2507 e Gemma-4-31B-it, com o prompt `prompts/contrast_verify_v1.txt`. Cada um precisa responder YES para: operação cumprida, resto preservado, coerência interna e naturalidade. A stance da fala reescrita sobre a proposição-alvo precisa ser a esperada (`NOT_ADDRESSED` nos `SHIFT_*`).

Reporta-se a concordância entre os verificadores. Um piloto de 20 itens verifica o formato antes da rodada completa; o piloto não altera critérios nem prompts, exceto para corrigir erro de formato, que seria registrado como desvio.

## Condições avaliadas

| Código | Descrição |
|---|---|
| A | end-to-end v1 (prompt congelado) |
| B | estruturado v1 com comparabilidade forçada |
| C | estruturado v1 com gate |
| D | gate desacoplado: extração por lado + comparação só das perguntas (`docs/decoupled_gate.md`) |
| D-forçado | a extração de D com comparabilidade forçada |
| **E** | **alvo ancorado:** a pergunta extraída do lado a (a mesma extração de D) e a fala do lado b, sem a fala nem a stance de a, vão numa chamada com o prompt `prompts/anchored_answer_v1.txt`. O modelo responde se b trata daquela pergunta e qual é a resposta de b. A relação sai de `derive_relation(det_a, det_b, same, stance_a, resposta_b)`, com `det_a` e `det_b` da extração de D. |
| E-forçado | E com comparabilidade forçada |

**Modelos:**
- Qwen2.5-72B, Llama-3.3-70B, gpt-oss-120b, Mistral-Small-3.2-24B, Nemotron-3-Ultra-550B e MiniMax-M3, em todas as condições;
- GLM-5.2 somente em D e E, por custo.

Todas as condições rodam em ordem cronológica, sobre os pares naturais e os itens aceitos.

## Métricas (por modelo × condição, com IC de Wilson 95%)

- **Recall de reversão:** entre os itens esperados `STANCE_REVERSED` (`REVERSE`, `ALIGN_REVERSE`), a fração prevista `STANCE_REVERSED`.
- **Falsa reversão:** entre os itens esperados diferentes de `STANCE_REVERSED`, a fração prevista `STANCE_REVERSED`. Reportada também por operação.
- **Falsa comparabilidade:** entre os itens esperados `INCOMPARABLE` (`SHIFT_*`, `REVERSE_ON_INCOMPARABLE`), a fração prevista `STANCE_MAINTAINED` ou `STANCE_REVERSED`. Reportada também por tipo de fronteira (H3).
- **Recall de comparáveis:** entre os itens esperados `MAINTAINED` ou `REVERSED`, a fração prevista `MAINTAINED` ou `REVERSED`.
- **Pares naturais:** acurácia da relação, recall e precisão de comparabilidade e falsas reversões, separados em dev (piloto) e teste (expansão).

## Orçamento e execução

- **Teto de gasto real:** US$ 12. Ao atingi-lo, a execução para e o estado parcial é reportado.
- **Cache:** respostas brutas em cache, reutilizando as já coletadas com prompts idênticos (extrações de D nos pares naturais).
- **Resiliência:** um alarme de travamento reinicia as execuções a partir do cache.
