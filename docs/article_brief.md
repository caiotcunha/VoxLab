# Brief para o artigo: onde estamos e aonde queremos chegar

*Estado em 2026-09-28, branch `testes-luisa`. Documento de referência para começar a redação; os números vêm dos arquivos citados.*

## 1. Aonde queremos chegar

**Tese provisória.** Detectar mudança de posição de um mesmo ator ao longo do tempo depende de um passo anterior e subestimado: decidir se duas falas tratam da **mesma proposição**. Nos modelos de linguagem atuais, esse passo, o comparability gate, cai num trade-off. Ou o sistema inventa reversões e aceita proposições diferentes como comparáveis, ou elimina esses erros e junto apaga as reversões verdadeiras. O trade-off se repete em modelos de famílias e tamanhos diferentes.

**Formato pretendido:** artigo de benchmark com contrast set.
- **Dados reais:** pares de falas do mesmo ator em audiências públicas da Câmara, com proveniência verificada em fontes oficiais e rótulos humanos adjudicados.
- **Contrast set** (Gardner et al., 2020): alterações controladas desses pares, com resposta conhecida por construção.

**Título de trabalho:** *"Changed their mind or changed the subject? Comparability as the bottleneck of longitudinal stance detection in Brazilian public hearings"*.

**Contribuições candidatas:**
1. **Recurso:** 47 pares com proveniência validada e gold humano (piloto 18, expansão 29), mais o contrast set.
2. **Achado principal:** o trade-off do gate, medido em 5 modelos (7 no plano) e três arquiteturas de pipeline (end-to-end, estruturado com gate, gate desacoplado).
3. **Diagnóstico do mecanismo:**
   - lendo as duas falas juntas, os modelos tratam "mudou a posição" como "mudou a proposição";
   - separando as falas, a stance vaza para a formulação da pergunta, e perguntas extraídas separadamente não se casam.
4. **Achado de anotação:** parte do desacordo de stance é só a polaridade da formulação da proposição. A concordância humana na expansão sobe de κ 0,27 para 0,54 quando isso é descontado.

**Público e venue:** NLP para ciências sociais e política, ou NLP em português (PROPOR, STIL), ou um workshop de avaliação ou recursos. A versão ampliada do contrast set é o que tornaria o trabalho competitivo fora desses nichos.

## 2. Ponto de partida (antes de hoje)

- **Seleção:** 206 audiências → 878 atores → 396 pares do mesmo ator → 58 candidatos por similaridade de tema.
- **Validação:** proveniência documental conferida nas fontes oficiais.
- **Gold:** 47 pares com duas anotações independentes e consenso. São 12 `STANCE_MAINTAINED`, 31 `INCOMPARABLE`, 3 incertos e **0 `STANCE_REVERSED`**.
- **Baselines com LLM** (Qwen2.5-72B, Llama-3.3-70B): o end-to-end (A) empata com o estruturado com gate (C), com acurácia de 0,59–0,69 na expansão.

**Problemas em aberto no início do dia:**
- sem reversões no gold, não havia como medir se o gate preserva as reversões reais;
- não se sabia por que o gate não superava o end-to-end.

## 3. O que fizemos hoje

Custo total de API: ~US$ 3,1, sem nenhuma anotação humana nova.

| # | Experimento | Resultado central | Doc |
|---|---|---|---|
| 1 | **Contrafactuais sintéticos** (39 aceitos de 67 gerados; DeepSeek-V3.1 gera, Qwen3-235B verifica) | Com gate, as falsas reversões em pares incomparáveis caem (de 3–5/17 para 0–1/17), mas o recall de reversões verdadeiras também cai (de 3–4/7 para 0–1/7). O end-to-end aceita proposição deslocada em 8/8. | `stress_and_canonicalization.md` |
| 2 | **Canonização de proposições** (dois juízes cegos à stance) | 5 dos 8 desacordos humanos de stance na expansão são só polaridade da formulação, e o κ vai de 0,27 para 0,54. Nenhum par comparável do gold esconde reversão. | idem |
| 3 | **Correção** | A auditoria de polaridade antiga comparava lados trocados em 16 dos 29 pares da expansão. As métricas de relação não são afetadas. | idem, e nota em `proposition_polarity_audit.md` |
| 4 | **Gate v2** (perguntas neutras de sim/não; dev → hash congelado → teste) | Negativo: move o limiar sem melhorar a discriminação, e a melhora no dev não se repete no teste. | `question_gate.md` |
| 5 | **Gate desacoplado + 3 modelos maiores** (GLM-5.2, Nemotron-3-Ultra, gpt-oss-120b) | Os pontos se agrupam por condição, não por modelo, e nenhum chega ao canto ideal. Desacoplar tira o vazamento da stance, mas sem alvo compartilhado as perguntas não se casam (recall de comparáveis cai a ~0 nos modelos grandes). | `decoupled_gate.md`, `figures/gate_tradeoff.png` |

**Figura central candidata:** `docs/figures/gate_tradeoff.png`. O eixo y é o recall de reversões; o eixo x é a falsa reversão (painel 1) ou a falsa comparabilidade (painel 2). Cada ponto é um par modelo × condição.

## 4. Próximo passo aprovado: contrast set v2

- **Mais itens:** ~400 candidatos, meta de ~230 aceitos. Reescrita dos dois lados e troca de proposição por tipo de fronteira (instrumento, população, objeto, escopo), o que dá a tipologia.
- **Duas operações novas:** "alinhar", que faz um par incomparável virar comparável, com e sem reversão. Assim as reversões vêm de 43 pares-fonte, e não de 12.
- **Qualidade com critérios definidos antes da rodada:** dois verificadores (Qwen3-235B e Gemma-4-31B), checagem de erros de cópia e uma checagem contra reescritas mais explícitas que a fala original sobre a proposição-alvo.
- **Nova condição E, alvo compartilhado:** a pergunta extraída do lado A é apresentada ao lado B, que não vê a fala nem a posição de A.
- **Modelos:** Qwen2.5, Llama-3.3, gpt-oss-120b, Mistral-Small-3.2, Nemotron-3-Ultra e MiniMax-M3, em todas as condições. GLM-5.2 só nas condições D e E.
- **Orçamento:** ~US$ 11, com teto e alarme de travamento. Um protocolo escrito antes da execução, depois um piloto de 20 itens, depois a rodada completa.
- **Depois:** aplicação ao corpus inteiro (396 pares, ~US$ 4) como uso descritivo, não como avaliação.

## 5. Esqueleto sugerido do artigo e onde está a evidência

1. **Introdução:** "mudou de ideia ou de assunto?", falsas reversões como risco concreto em análises automáticas de coerência política.
2. **Trabalho relacionado:** stance detection, detecção de mudança de posição, contrast sets e counterfactual evaluation, e a literatura de governismo no Brasil (em `docs/literature_review.md`, na branch `party-alignment`).
3. **Dados:** PublicHearingBR, seleção de pares, proveniência (`provenance_validation.md`, `dataset_expansion.md`), anotação e concordância (`semantic_agreement.md`, `semantic_consensus_analysis.md`) e o artefato de polaridade (§2 de `stress_and_canonicalization.md`).
4. **Tarefa e pipelines:** as condições A, B, C, D e E, com derivação determinística da relação (`agreement.derive_relation`).
5. **Contrast set:** operações, geração, verificação e aceitação (versão atual em `stress_and_canonicalization.md`; a v2 virá com o próprio protocolo).
6. **Resultados:** pares naturais (`prospective_evaluation`, `decoupled_gate.md`), contrast set e figura do trade-off, e a análise por tipo de fronteira (v2).
7. **Análise do mecanismo:** vazamento de stance e granularidade das perguntas, com os exemplos já documentados.
8. **Limitações:**
   - nenhuma reversão natural; limite superior de ~25% entre os pares comparáveis;
   - n pequeno;
   - validade dos contrafactuais sintéticos;
   - verificadores LLM;
   - unidade de análise (trecho validado versus turno completo).

## 6. Riscos para a redação

- **Não afirmar detecção de reversão real.** O gold só sustenta que falsas reversões são um risco e que reversões são raras nos pares comparáveis examinados.
- **Os resultados do contrast set medem o comportamento dos modelos sob alterações controladas.** Não são taxas de erro no mundo real.
- **Reportar os resultados negativos (gate v2, desacoplado).** Eles são a evidência de que o trade-off não se resolve com reformulação de prompt.
