# Eval-riport – 4. futás

| | |
|---|---|
| Időpont | 2026-10-27 14:39 UTC |
| Modell | `claude-sonnet-5-5` |
| Prompt | `text_to_sql.v1` |
| Few-shot | nincs |
| Commit | `319769d` |
| Címke | v1, few-shot 0, pontosított kérdéssor |

## Fő számok

| Metrika | Érték | Cél |
|---|---|---|
| Végrehajtási pontosság (arany sor) | 48/50 (96,0%) | ≥ 80,0% |
| Érvényes SQL aránya | 100,0% | |
| Indokolatlan elutasítás | 0,0% | |
| Önjavítással lett helyes | 0 | |
| Elutasítás (rosszindulatú sor) | – | 100,0% |
| Késleltetés p50 / p95 | 3,2 s / 5,1 s | |
| Token kérdésenként (be / ki) | 6 870 / 306 | |
| Kísérlet kérdésenként | 1,00 | |

## Nehézség szerint

| Nehézség | Helyes |
|---|---|
| easy | 16/16 (100,0%) |
| medium | 22/23 (95,7%) |
| hard | 10/11 (90,9%) |

## Címke szerint

| Címke | Helyes |
|---|---|
| aggregation | 44/46 (95,7%) |
| branch | 3/4 (75,0%) |
| filter | 12/12 (100,0%) |
| join | 10/11 (90,9%) |
| ranking | 5/6 (83,3%) |
| subquery | 2/2 (100,0%) |
| time | 25/26 (96,2%) |
| window | 4/4 (100,0%) |

## Hibás válaszok

### `branch_top_merchants_q3` (golden)

> Az utolsó negyedévben melyik 5 kereskedőnél költöttek a legtöbbet a fiókunk ügyfelei?

- Állapot: `ok`, 1 kísérlet
- Ok: nincs egyező oszlop ehhez: merchant_name, spend_huf

```sql
WITH q AS (
  SELECT
    DATE_TRUNC('QUARTER', business_date) - INTERVAL '3 MONTHS' AS start_q,
    DATE_TRUNC('QUARTER', business_date) AS end_q
  FROM business_day
)
SELECT
  t.merchant_id,
  t.merchant_name,
  t.merchant_category,
  -SUM(t.amount_huf) AS card_spend_huf
FROM transactions AS t, q
WHERE
  t.channel = 'card'
  AND t.merchant_id IS NOT NULL
  AND t.amount < 0
  AND t.booked_at >= q.start_q
  AND t.booked_at < q.end_q
GROUP BY
  t.merchant_id,
  t.merchant_name,
  t.merchant_category
ORDER BY
  card_spend_huf DESC
LIMIT 5
```

### `overdue_amount_by_branch` (golden)

> Mennyi a lejárt, meg nem fizetett hiteltartozás összege fiókonként? A fiók nevével.

- Állapot: `ok`, 1 kísérlet
- Ok: 20 sor, a várt 19 helyett

```sql
SELECT
  b.branch_id,
  b.name AS branch_name,
  SUM(l.overdue_amount) AS overdue_amount_huf
FROM loans AS l
JOIN branches AS b
  ON b.branch_id = l.branch_id
WHERE
  l.status = 'active'
GROUP BY
  b.branch_id,
  b.name
ORDER BY
  overdue_amount_huf DESC
LIMIT 200
```
