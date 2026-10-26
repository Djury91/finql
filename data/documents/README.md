# Szintetikus banki dokumentumok

A FinQL dokumentumkeresésének (RAG) forrása: a kitalált Minta Bank Zrt. díjjegyzékei,
termékfeltételei és belső szabályzatai. **Minden adat kitalált.** A számok a szintetikus
banki adatbázishoz igazodnak (kamatok, termékek, szegmensek, késedelmi sávok), nem egy valódi
bankéhoz, és jogi vagy pénzügyi tanácsnak sem tekinthetők.

Betöltés: `uv run finql ingest`. Csak a változott fájlokat dolgozza fel újra, a törölt fájlok
dokumentumait törli. Ezt a fájlt kihagyja.

Minden dokumentum YAML-fejléccel kezdődik:

```yaml
---
title: Lakossági díjjegyzék
doc_type: fee_schedule      # fee_schedule, rate_notice, product_terms, policy, procedure, glossary
access_level: general       # general: minden munkatárs; internal: elemző, auditor, admin
effective_from: 2026-01-01
---
```

A szöveg `##` és `###` címsorai a szakaszok: a darabolás ezek mentén vág, és a válasz ezekre
hivatkozik.
