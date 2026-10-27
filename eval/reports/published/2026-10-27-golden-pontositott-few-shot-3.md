# Eval-riport – 5. futás

| | |
|---|---|
| Időpont | 2026-10-27 14:40 UTC |
| Modell | `claude-sonnet-5-5` |
| Prompt | `text_to_sql.v1` |
| Few-shot | 3 példa (`voyage-4`) |
| Commit | `319769d` |
| Címke | v1, few-shot 3, pontosított kérdéssor |

## Fő számok

| Metrika | Érték | Cél |
|---|---|---|
| Végrehajtási pontosság (arany sor) | 49/50 (98,0%) | ≥ 80,0% |
| Érvényes SQL aránya | 100,0% | |
| Indokolatlan elutasítás | 0,0% | |
| Önjavítással lett helyes | 0 | |
| Elutasítás (rosszindulatú sor) | – | 100,0% |
| Késleltetés p50 / p95 | 3,2 s / 5,1 s | |
| Token kérdésenként (be / ki) | 7 411 / 282 | |
| Kísérlet kérdésenként | 1,00 | |

## Nehézség szerint

| Nehézség | Helyes |
|---|---|
| easy | 16/16 (100,0%) |
| medium | 23/23 (100,0%) |
| hard | 10/11 (90,9%) |

## Címke szerint

| Címke | Helyes |
|---|---|
| aggregation | 45/46 (97,8%) |
| branch | 4/4 (100,0%) |
| filter | 12/12 (100,0%) |
| join | 10/11 (90,9%) |
| ranking | 6/6 (100,0%) |
| subquery | 2/2 (100,0%) |
| time | 25/26 (96,2%) |
| window | 4/4 (100,0%) |

## Hibás válaszok

### `leisure_spend_share_by_segment_2025` (golden)

> A prémium és a lakossági ügyfelek 2025-ös kártyás költésének szegmensenként hány százaléka ment éttermekre, szállásra és utazásra?

- Állapot: `ok`, 1 kísérlet
- Ok: nincs egyező oszlop ehhez: leisure_pct

```sql
SELECT
  c.segment,
  ROUND(
    100 * SUM(-t.amount_huf) FILTER(WHERE
      t.merchant_category = 'restaurant') / SUM(-t.amount_huf),
    1
  ) AS restaurant_pct,
  ROUND(
    100 * SUM(-t.amount_huf) FILTER(WHERE
      t.merchant_category = 'hotel') / SUM(-t.amount_huf),
    1
  ) AS hotel_pct,
  ROUND(
    100 * SUM(-t.amount_huf) FILTER(WHERE
      t.merchant_category = 'travel') / SUM(-t.amount_huf),
    1
  ) AS travel_pct,
  -SUM(t.amount_huf) AS card_spend_huf
FROM transactions AS t
JOIN accounts AS a
  USING (account_id)
JOIN customers AS c
  USING (customer_id)
WHERE
  t.channel = 'card'
  AND t.amount < 0
  AND c.segment IN ('premium', 'retail')
  AND t.booked_at >= '2025-01-01'
  AND t.booked_at < '2026-01-01'
GROUP BY
  c.segment
ORDER BY
  c.segment
LIMIT 200
```
