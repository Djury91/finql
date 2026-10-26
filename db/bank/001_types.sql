-- Zárt értékkészletek enumként: a hibás érték már beszúráskor elbukik,
-- és az LLM-kontextusban is pontosan felsorolhatók az értékek.

CREATE TYPE bank.customer_type    AS ENUM ('individual', 'company');
CREATE TYPE bank.customer_segment AS ENUM ('retail', 'premium', 'sme', 'corporate');
CREATE TYPE bank.risk_rating      AS ENUM ('low', 'medium', 'high');

CREATE TYPE bank.product_type AS ENUM (
    'current_account', 'savings', 'credit_card', 'personal_loan', 'mortgage', 'business_loan'
);
CREATE TYPE bank.account_status AS ENUM ('active', 'frozen', 'closed');

CREATE TYPE bank.card_type   AS ENUM ('debit', 'credit');
CREATE TYPE bank.card_status AS ENUM ('active', 'blocked', 'expired');

CREATE TYPE bank.tx_channel AS ENUM ('card', 'transfer', 'atm', 'direct_debit', 'fee', 'interest');

CREATE TYPE bank.loan_status AS ENUM ('active', 'closed');
