-- Ki olvashatja a bank sémát? Egyedül a finql_analytics (az analytics nézetek tulajdonosa).
-- Az alkalmazás (finql_app) és az LLM (finql_llm_reader) itt semmihez nem fér hozzá.
--
-- Szándékosan táblánként adjuk a jogot, nem ON ALL TABLES IN SCHEMA formában: az utóbbi a
-- havi partíciókra is SELECT-et adna. Partíció közvetlen olvasásakor viszont a szülőtábla
-- RLS-policyja nem érvényesül, csak a partícióé, így az RLS megkerülhető lenne.

GRANT USAGE ON SCHEMA bank TO finql_analytics;

GRANT SELECT ON
    bank.branches,
    bank.products,
    bank.merchants,
    bank.fx_rates,
    bank.business_day,
    bank.customers,
    bank.accounts,
    bank.cards,
    bank.loans,
    bank.loan_installments,
    bank.transactions
TO finql_analytics;
