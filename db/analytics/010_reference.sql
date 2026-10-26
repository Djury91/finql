-- Törzsadatok: nem ügyfélhez kötöttek, minden felhasználó látja őket.

CREATE VIEW analytics.branches AS
SELECT branch_id, code, name, city, region
FROM bank.branches;

CREATE VIEW analytics.products AS
SELECT product_id, product_type, name, currency, interest_rate
FROM bank.products;

CREATE VIEW analytics.merchants AS
SELECT merchant_id, name, mcc, category, city, country
FROM bank.merchants;

CREATE VIEW analytics.fx_rates AS
SELECT rate_date, currency, rate_to_huf
FROM bank.fx_rates;

CREATE VIEW analytics.business_day AS
SELECT business_date
FROM bank.business_day;
