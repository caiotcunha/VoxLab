# Gate v2: comparabilidade julgada por perguntas neutras

**Resultado negativo, registrado como tal.** O v2 não generalizou para o conjunto de teste. Ele desloca o ponto de operação do gate, mas não resolve a confusão entre mudança de posição e mudança de proposição.

## Motivação

O estresse contrafactual (`docs/stress_and_canonicalization.md`) mostrou que o gate v1 transforma reversões verdadeiras em `INCOMPARABLE`: quando a stance muda, os modelos respondem `same_proposition=NO`.

O v2 muda somente o prompt estruturado:
- cada lado recebe uma **pergunta neutra de sim ou não**, que não revela a resposta do falante;
- a comparabilidade é decidida **olhando só as perguntas**. O prompt diz explicitamente que responder à mesma pergunta de formas opostas continua sendo a mesma pergunta;
- a stance é a resposta à pergunta.

O schema JSON, o parser e `agreement.derive_relation` são os do v1, sem alteração. Os modelos avaliados são os mesmos: Qwen2.5-72B e Llama-3.3-70B.

## Protocolo

Tudo abaixo foi fixado antes da primeira chamada ao v2.

- **Dev:** os 18 pares do piloto e as 16 reescritas aceitas derivadas deles.
- **Teste:** os 29 pares da expansão e as 23 reescritas derivadas deles.
- **Congelamento:** depois do dev, o hash do prompt foi congelado (`question_gate_freeze.json`, sha256 `b7d1a4cb…`). O código bloqueia o teste se o prompt mudar.
- **Revisões:** o protocolo permitia uma revisão no dev, mas ela não foi usada. O prompt testado é o primeiro.
- **Ressalva:** o v2 foi motivado por resultados de estresse que incluíam reescritas de pares da expansão. O teste é cego ao ajuste do v2, mas não à análise de falhas que o originou.

Custo: 172 chamadas, US$ 0,16.

## Resultados

### Pares naturais (gold humano)

| Split | Modelo | Acurácia v1 A | Acurácia v1 C | Acurácia **v2 C** | Recall de comparável v1 → v2 | Precisão de comparável v1 → v2 |
|---|---|---:|---:|---:|---:|---:|
| dev (18) | Qwen | 0,78 | 0,78 | 0,78 | 0,80 → 1,00 | 1,00 → 0,83 |
| dev (18) | Llama | 0,83 | 0,72 | 0,78 | 0,60 → 0,80 | 1,00 → 0,80 |
| teste (29) | Qwen | 0,59 | 0,62 | 0,62 | 0,57 → 1,00 | 0,50 → 0,47 |
| teste (29) | Llama | 0,69 | 0,66 | **0,59** | 0,29 → 0,57 | 0,40 → 0,40 |

Nenhuma condição produziu falsa reversão em pares naturais.

### Contrafactuais (k/n)

| Split | Modelo | Métrica | v1 A | v1 C | v2 B (sem gate) | **v2 C** |
|---|---|---|---:|---:|---:|---:|
| dev | Qwen | recall de reversão | 2/3 | 1/3 | 2/3 | 2/3 |
| dev | Llama | recall de reversão | 1/3 | 0/3 | 1/3 | 1/3 |
| teste | Qwen | recall de reversão | 2/4 | 0/4 | 1/4 | 1/4 |
| teste | Llama | recall de reversão | 2/4 | 0/4 | 2/4 | 0/4 |
| teste | Qwen | falsa reversão em incomparáveis | 2/11 | 1/11 | 3/11 | 2/11 |
| teste | Llama | falsa reversão em incomparáveis | 1/11 | 0/11 | 3/11 | 1/11 |
| teste | Qwen | falsa comparabilidade (SHIFT) | 4/4 | 1/4 | 4/4 | 4/4 |
| teste | Llama | falsa comparabilidade (SHIFT) | 4/4 | 0/4 | 4/4 | 2/4 |

No dev, as duas condições têm 0/6 falsas reversões em incomparáveis e 0/3 em negação de polaridade.

## Leitura

1. **O v2 desloca o gate para "comparável" em vez de melhorá-lo.**
   - O recall de pares comparáveis sobe nos dois modelos e nos dois splits: no teste, o Qwen vai a 1,00.
   - A precisão não acompanha, e o v2 perde o que o v1 fazia bem: no teste, a falsa comparabilidade em proposições deslocadas volta a 4/4 (Qwen) e 2/4 (Llama).
   - É o mesmo trade-off do v1, com o ponto de operação em outro lugar.
2. **No Qwen, o gargalo passa para a leitura de stance.**
   - Nas 4 reversões do teste, o v2 responde "mesma pergunta" em 3 casos; o v1 respondia "mesma proposição" em apenas 1. A confusão do gate diminui.
   - Mas o Qwen lê FAVOR/FAVOR em 3 desses 4 casos, e a reversão continua não detectada.
3. **No Llama, o problema do gate persiste.** Ele continua respondendo "pergunta diferente" em 3 de 4 reversões do teste (4 de 4 no v1), e a acurácia nos pares naturais cai de 0,66 para 0,59.
4. **A melhora do dev não se repetiu no teste.** Com 18 pares e 3 reversões sintéticas, o dev era pequeno demais para escolher prompts, o que confirma o aviso do protocolo.

## Conclusão

Com modelos de ~70B e um único prompt estruturado, separar "mesma questão" de "mesma resposta" não se resolve reformulando o prompt. Os dois modos de falha medidos no estresse (descartar reversões e aceitar proposições deslocadas) se comportam como dois lados de um mesmo limiar. O prompt move o limiar; não melhora a discriminação.

Hipóteses para próximos passos:
- desacoplar as chamadas: julgar a comparabilidade numa chamada que não vê as falas, só as duas perguntas;
- usar modelos maiores;
- treinar um classificador nos contrafactuais.

## Artefatos e reprodução

```
prompts/structured_extraction_v2_question_gate.txt
src/voxlab/question_gate.py, tests/test_question_gate.py
data/processed/question_gate/question_gate_{dev,test}_{natural,synthetic}.csv
data/processed/question_gate/question_gate_{dev,test}_metrics.json
data/processed/question_gate/question_gate_freeze.json
data/processed/llm_raw_outputs/stress/v2_question_gate_*.json   (172 respostas brutas)
```

```bash
PYTHONPATH=src python3 -m voxlab.question_gate --split dev --execute    # usa o cache
PYTHONPATH=src python3 -m voxlab.question_gate --freeze
PYTHONPATH=src python3 -m voxlab.question_gate --split test --execute
```
