-- Tranzakciók forintosított összeggel és kereskedőadatokkal.
-- A közlemény (description) kimarad: valós adatban partnernevet, személyes adatot tartalmazhat.

CREATE VIEW analytics.transactions AS
SELECT t.transaction_id,
       t.account_id,
       t.branch_id,
       t.booked_at,
       (t.booked_at AT TIME ZONE 'Europe/Budapest')::date AS booked_date,
       t.amount,
       t.currency,
       -- Hiányzó árfolyamnál NULL (nem csendben 1): az fx_rates minden naptári napot lefed.
       CASE WHEN t.currency = 'HUF' THEN t.amount ELSE round(t.amount * fx.rate_to_huf, 2) END AS amount_huf,
       t.channel,
       t.merchant_id,
       m.name     AS merchant_name,
       m.category AS merchant_category
FROM bank.transactions t
LEFT JOIN bank.merchants m ON m.merchant_id = t.merchant_id
LEFT JOIN bank.fx_rates fx
       ON fx.currency = t.currency
      AND fx.rate_date = (t.booked_at AT TIME ZONE 'Europe/Budapest')::date;
