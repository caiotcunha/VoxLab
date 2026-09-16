# Metadados oficiais de eventos

Arquivos CSV anuais de eventos da Câmara dos Deputados, consultados em 2026-09-16:

| Arquivo local | Origem | SHA-256 |
|---|---|---|
| `eventos-2022.csv` | <https://dadosabertos.camara.leg.br/arquivos/eventos/csv/eventos-2022.csv> | `915ebce7b9a3b87607f8c68af748ec022c0423ba49ca47118748c9229ac970de` |
| `eventos-2023.csv` | <https://dadosabertos.camara.leg.br/arquivos/eventos/csv/eventos-2023.csv> | `134ff92b32e582d5497bb30d8292bfdf161c4225c46c2c6c058b0bbfa3018b05` |
| `eventos-2024.csv` | <https://dadosabertos.camara.leg.br/arquivos/eventos/csv/eventos-2024.csv> | `a6f8a6311b51330da7b9ef5a04eb9cb0265c12f9fe7c917d11ce977e8984287d` |

O CSV usa separador `;` e contém `id`, `uri`, `dataHoraInicio`, `descricao` e `situacao`, entre outros campos. A [documentação oficial da API](https://dadosabertos.camara.leg.br/swagger/api.html) descreve os eventos. Cada `uri` no CSV aponta para o evento na API. Estes arquivos são instantâneos: novas versões da fonte podem mudar; verifique os hashes antes de reproduzir a análise.

A associação entre IDs locais do PublicHearingBR e IDs oficiais foi revista manualmente e está em `data/annotations/pilot_event_crosswalk.csv`. O ID local não é um ID oficial de audiência.
