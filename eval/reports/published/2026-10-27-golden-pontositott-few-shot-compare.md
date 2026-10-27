# Eval-összevetés: 4. és 5. futás

| | 4. futás | 5. futás |
|---|---|---|
| Modell | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| Prompt | `text_to_sql.v1` | `text_to_sql.v1` |
| Few-shot | nincs | 3 példa (`voyage-4`) |
| Végrehajtási pontosság | 96,0% | 98,0% |
| Érvényes SQL aránya | 100,0% | 100,0% |
| Elutasítás (rosszindulatú) | – | – |
| Késleltetés p50 / p95 | 3,2 s / 5,1 s | 3,2 s / 5,1 s |
| Token kérdésenként | 7 175 | 7 693 |

## Javult (2)

- `branch_top_merchants_q3` (golden): Az utolsó negyedévben melyik 5 kereskedőnél költöttek a legtöbbet a fiókunk ügyfelei?
- `overdue_amount_by_branch` (golden): Mennyi a lejárt, meg nem fizetett hiteltartozás összege fiókonként? A fiók nevével.

## Romlott (1)

- `leisure_spend_share_by_segment_2025` (golden): A prémium és a lakossági ügyfelek 2025-ös kártyás költésének szegmensenként hány százaléka ment éttermekre, szállásra és utazásra?
