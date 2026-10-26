-- Az LLM számára kiajánlott szemantikai réteg: nézetek, személyes adat (PII) nélkül.
--
-- Minden nézet tulajdonosa a finql_analytics (099_ownership_grants.sql, utolsóként). A nézet a tulajdonosa
-- nevében olvassa a bank táblákat, és mivel a finql_analytics nem táblatulajdonos, az RLS
-- érvényes rá. Az LLM-szerepkör (finql_llm_reader) csak ezeket a nézeteket olvashatja.

CREATE SCHEMA analytics;
REVOKE ALL ON SCHEMA analytics FROM PUBLIC;

-- CREATE: az ALTER VIEW … OWNER TO feltétele, hogy az új tulajdonos létrehozhasson objektumot
-- a sémában. A finql_analytics NOLOGIN, csak a finql_owner léphet a nevében.
GRANT USAGE, CREATE ON SCHEMA analytics TO finql_analytics;
GRANT USAGE ON SCHEMA analytics TO finql_llm_reader;

COMMENT ON SCHEMA analytics IS
    'Minta Bank Zrt. elemzési nézetei. Személyes adatot (név, adóazonosító, teljes IBAN, születési dátum) nem tartalmaznak. A fiókhoz kötött nézetek csak a felhasználó jogosultsága szerinti fiók(ok) sorait mutatják.';
