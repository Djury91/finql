-- PostgreSQL-bővítmények.
--
-- Futtatja: `finql db bootstrap`, a szerepkörök után. A pgvector nem „trusted” bővítmény, ezért
-- csak superuser hozhatja létre; az Alembic-migrációk (finql_owner) már csak használják.
-- Idempotens, többször is futtatható.

-- Saját séma: a public sémát lezártuk (001_roles.sql), és így a bővítmény objektumai
-- (típus, operátorok, függvények) nem keverednek a mieinkkel.
CREATE SCHEMA IF NOT EXISTS extensions;
REVOKE ALL ON SCHEMA extensions FROM PUBLIC;
-- Az LLM-szerepkör szándékosan nem kap jogot: neki csak az analytics nézetek kellenek.
GRANT USAGE ON SCHEMA extensions TO finql_owner, finql_app;

-- vector(1024): a few-shot példák (4. fázis) és a dokumentumrészletek (5. fázis) embeddingje.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- A `vector` típus és a `<=>` operátor sémanév nélkül is feloldható legyen. Adatbázisszintű
-- beállítás: a finql_llm_reader saját, szerepkörszintű search_path-ja (analytics) ezt felülírja.
DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET search_path = "$user", public, extensions', current_database()
    );
END
$$;
