-- Indexek. A PostgreSQL az FK-oszlopokat nem indexeli automatikusan, ezért a JOIN-okhoz
-- és a szülő oldali törléshez szükségeseket itt hozzuk létre.
--
-- A bank.transactions indexeit és FK-it a seed nagy betöltés előtt eldobja, utána
-- ugyanezekkel a definíciókkal újra létrehozza (pg_get_indexdef / pg_get_constraintdef).
-- Ezt a fájlt ezért nem kell szinkronban tartani a seed kódjával.

CREATE INDEX customers_home_branch_idx ON bank.customers (home_branch_id);

CREATE INDEX accounts_customer_idx ON bank.accounts (customer_id);
CREATE INDEX accounts_branch_idx   ON bank.accounts (branch_id);
CREATE INDEX accounts_product_idx  ON bank.accounts (product_id);

CREATE INDEX cards_account_idx ON bank.cards (account_id);

-- Particionált táblán az index minden (meglévő és jövőbeli) partíción létrejön.
CREATE INDEX transactions_account_booked_idx ON bank.transactions (account_id, booked_at);
CREATE INDEX transactions_branch_booked_idx  ON bank.transactions (branch_id, booked_at);
CREATE INDEX transactions_merchant_idx       ON bank.transactions (merchant_id)
    WHERE merchant_id IS NOT NULL;
CREATE INDEX transactions_card_idx           ON bank.transactions (card_id)
    WHERE card_id IS NOT NULL;
