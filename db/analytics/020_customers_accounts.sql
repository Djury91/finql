-- Ügyfelek, számlák, kártyák. A sorszűrést az alaptáblák RLS-e végzi, nem a nézet: az RLS-feltétel
-- mindig a felhasználó (nem leakproof) szűrői előtt fut. Ezért itt nem kell security_barrier, amely
-- megakadályozná, hogy a tervező a szűrőket (pl. channel = 'card') a nézet alá tolja.
-- Kihagyott PII: név, adóazonosító, születési dátum (helyette korcsoport), teljes IBAN, kártyaszám vége.

CREATE VIEW analytics.customers AS
SELECT c.customer_id,
       c.customer_type,
       c.segment,
       c.city,
       CASE
           WHEN c.birth_date IS NULL THEN NULL
           WHEN age(bd.business_date, c.birth_date) < interval '26 years' THEN '18-25'
           WHEN age(bd.business_date, c.birth_date) < interval '36 years' THEN '26-35'
           WHEN age(bd.business_date, c.birth_date) < interval '46 years' THEN '36-45'
           WHEN age(bd.business_date, c.birth_date) < interval '56 years' THEN '46-55'
           WHEN age(bd.business_date, c.birth_date) < interval '66 years' THEN '56-65'
           ELSE '66+'
       END AS age_band,
       c.home_branch_id,
       c.risk_rating,
       (c.created_at AT TIME ZONE 'Europe/Budapest')::date AS customer_since,
       EXISTS (
           SELECT FROM bank.accounts a
           WHERE a.customer_id = c.customer_id AND a.status <> 'closed'
       ) AS is_active
FROM bank.customers c
CROSS JOIN bank.business_day bd;

CREATE VIEW analytics.accounts AS
SELECT a.account_id,
       a.customer_id,
       a.branch_id,
       a.product_id,
       p.product_type,
       p.name               AS product_name,
       a.currency,
       a.status,
       a.status <> 'closed' AS is_active,
       a.opened_at,
       a.closed_at,
       a.credit_limit,
       'HU** **** **** **** **** **** ' || right(a.iban, 4) AS iban_masked
FROM bank.accounts a
JOIN bank.products p USING (product_id);

CREATE VIEW analytics.cards AS
SELECT card_id, account_id, card_type, status, issued_at, expires_at
FROM bank.cards;
