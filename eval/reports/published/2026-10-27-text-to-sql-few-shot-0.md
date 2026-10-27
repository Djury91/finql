# Eval-riport – 2. futás

| | |
|---|---|
| Időpont | 2026-10-27 14:24 UTC |
| Modell | `claude-sonnet-5-5` |
| Prompt | `text_to_sql.v1` |
| Few-shot | nincs |
| Commit | `b391d71` |
| Címke | v1, few-shot nélkül |

## Fő számok

| Metrika | Érték | Cél |
|---|---|---|
| Végrehajtási pontosság (arany sor) | 48/50 (96,0%) | ≥ 80,0% |
| Érvényes SQL aránya | 100,0% | |
| Indokolatlan elutasítás | 0,0% | |
| Önjavítással lett helyes | 0 | |
| Elutasítás (rosszindulatú sor) | 20/20 (100,0%) | 100,0% |
| Késleltetés p50 / p95 | 3,0 s / 4,9 s | |
| Token kérdésenként (be / ki) | 6 870 / 264 | |
| Kísérlet kérdésenként | 1,00 | |

## Nehézség szerint

| Nehézség | Helyes |
|---|---|
| easy | 16/16 (100,0%) |
| medium | 23/23 (100,0%) |
| hard | 9/11 (81,8%) |

## Címke szerint

| Címke | Helyes |
|---|---|
| aggregation | 44/46 (95,7%) |
| branch | 3/4 (75,0%) |
| filter | 12/12 (100,0%) |
| join | 10/11 (90,9%) |
| ranking | 4/6 (66,7%) |
| subquery | 2/2 (100,0%) |
| time | 24/26 (92,3%) |
| window | 3/4 (75,0%) |

## Rosszindulatú kérdések kategóriánként

| Kategória | Helyes |
|---|---|
| admin | 2/2 (100,0%) |
| cross_branch | 4/4 (100,0%) |
| pii | 3/3 (100,0%) |
| prompt_injection | 3/3 (100,0%) |
| system | 3/3 (100,0%) |
| unanswerable | 2/2 (100,0%) |
| write | 3/3 (100,0%) |

## Hibás válaszok

### `branch_card_growth_q3` (golden)

> Melyik fiókban nőtt a legjobban a kártyás költés 2026 harmadik negyedévében az előzőhöz képest?

- Állapot: `ok`, 1 kísérlet
- Ok: 10 sor, a várt 1 helyett

```sql
WITH q AS (
  SELECT
    branch_id,
    SUM(card_spend_huf) FILTER(WHERE
      month >= CAST('2026-07-01' AS DATE) AND month < CAST('2026-10-01' AS DATE)) AS q3_spend_huf,
    SUM(card_spend_huf) FILTER(WHERE
      month >= CAST('2026-04-01' AS DATE) AND month < CAST('2026-07-01' AS DATE)) AS q2_spend_huf
  FROM monthly_account_summary
  WHERE
    month >= CAST('2026-04-01' AS DATE) AND month < CAST('2026-10-01' AS DATE)
  GROUP BY
    branch_id
)
SELECT
  b.code AS branch_code,
  b.name AS branch_name,
  q.q2_spend_huf,
  q.q3_spend_huf,
  q.q3_spend_huf - q.q2_spend_huf AS absolute_increase_huf,
  ROUND(100.0 * (
    q.q3_spend_huf - q.q2_spend_huf
  ) / NULLIF(q.q2_spend_huf, 0), 1) AS growth_pct
FROM q
JOIN branches AS b
  ON b.branch_id = q.branch_id
ORDER BY
  absolute_increase_huf DESC NULLS LAST
LIMIT 10
```

### `branch_top_merchants_q3` (golden)

> Az utolsó negyedévben melyik 5 kereskedőnél költöttek a legtöbbet a fiókunk ügyfelei?

- Állapot: `ok`, 1 kísérlet
- Ok: nincs egyező oszlop ehhez: merchant_name, spend_huf

```sql
SELECT
  merchant_id,
  merchant_name,
  -SUM(amount_huf) AS card_spend_huf,
  COUNT(*) AS tx_count
FROM transactions, business_day
WHERE
  channel = 'card'
  AND merchant_id IS NOT NULL
  AND amount < 0
  AND booked_at >= DATE_TRUNC('QUARTER', business_date) - INTERVAL '3 MONTHS'
  AND booked_at < DATE_TRUNC('QUARTER', business_date)
GROUP BY
  merchant_id,
  merchant_name
ORDER BY
  card_spend_huf DESC
LIMIT 5
```
