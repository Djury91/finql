-- Havi számlaösszesítő: materializált, mert a 2 milliós tranzakciótáblán minden alkalommal
-- újraszámolni lassú lenne.
--
-- Miért a bank sémában van, és miért kell elé egy nézet? A materializált nézet pillanatfelvétel:
-- a lekérdezésekor az alaptáblák RLS-e NEM érvényesül, és materializált nézetre RLS-policy sem
-- tehető. Ha az LLM közvetlenül olvashatná, a fiókvezető minden fiók adatát látná. Ezért a nyers
-- összesítőt a táblatulajdonos birtokolja (a seed frissíti), az LLM pedig csak a lenti nézeten
-- keresztül éri el, amely ugyanazzal a fiókfeltétellel szűr, mint a policy-k.

-- Az amount_huf ugyanaz a kifejezés, mint az analytics.transactions nézetben. Szándékosan nem a
-- nézetből olvasunk: az RLS-es, és a frissítés kontextus nélkül futna, vagyis 0 sort látna.
CREATE MATERIALIZED VIEW bank.monthly_account_summary AS
SELECT t.account_id,
       t.branch_id,
       date_trunc('month', t.booked_at AT TIME ZONE 'Europe/Budapest')::date AS month,
       count(*) AS tx_count,
       coalesce(sum(t.amount_huf) FILTER (WHERE t.amount > 0), 0)        AS inflow_huf,
       coalesce(-sum(t.amount_huf) FILTER (WHERE t.amount < 0), 0)       AS outflow_huf,
       coalesce(-sum(t.amount_huf) FILTER (WHERE t.channel = 'card'), 0) AS card_spend_huf
FROM (
    SELECT tx.account_id, tx.branch_id, tx.booked_at, tx.amount, tx.channel,
           CASE WHEN tx.currency = 'HUF' THEN tx.amount
                ELSE round(tx.amount * fx.rate_to_huf, 2) END AS amount_huf
    FROM bank.transactions tx
    LEFT JOIN bank.fx_rates fx
           ON fx.currency = tx.currency
          AND fx.rate_date = (tx.booked_at AT TIME ZONE 'Europe/Budapest')::date
) t
GROUP BY 1, 2, 3;

-- Egyedi index: kell a REFRESH … CONCURRENTLY-hez (frissítés olvasók blokkolása nélkül).
CREATE UNIQUE INDEX monthly_account_summary_uq ON bank.monthly_account_summary (account_id, month);
CREATE INDEX monthly_account_summary_branch_idx ON bank.monthly_account_summary (branch_id, month);

GRANT SELECT ON bank.monthly_account_summary TO finql_analytics;

CREATE VIEW analytics.monthly_account_summary WITH (security_barrier = true) AS
SELECT account_id, branch_id, month, tx_count, inflow_huf, outflow_huf, card_spend_huf
FROM bank.monthly_account_summary
WHERE (SELECT app_ctx.all_branches()) OR branch_id = (SELECT app_ctx.branch_id());
