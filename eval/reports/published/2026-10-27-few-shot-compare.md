# Eval-összevetés: 2. és 3. futás

| | 2. futás | 3. futás |
|---|---|---|
| Modell | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| Prompt | `text_to_sql.v1` | `text_to_sql.v1` |
| Few-shot | nincs | 3 példa (`voyage-4`) |
| Végrehajtási pontosság | 96,0% | 96,0% |
| Érvényes SQL aránya | 100,0% | 100,0% |
| Elutasítás (rosszindulatú) | 100,0% | 100,0% |
| Késleltetés p50 / p95 | 3,0 s / 4,9 s | 3,3 s / 4,9 s |
| Token kérdésenként | 7 134 | 7 660 |

## Javult (2)

- `branch_card_growth_q3` (golden): Melyik fiókban nőtt a legjobban a kártyás költés 2026 harmadik negyedévében az előzőhöz képest?
- `branch_top_merchants_q3` (golden): Az utolsó negyedévben melyik 5 kereskedőnél költöttek a legtöbbet a fiókunk ügyfelei?

## Romlott (2)

- `leisure_spend_share_by_segment_2025` (golden): A prémium és a lakossági ügyfelek 2025-ös kártyás költésének hány százaléka ment éttermekre, szállásra és utazásra?
- `overdue_amount_by_branch` (golden): Mennyi a lejárt, meg nem fizetett hiteltartozás összege fiókonként? A fiók nevével.
