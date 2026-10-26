-- Adatbázis-szerepkörök és adatbázisszintű jogok.
--
-- Futtatja: `finql db bootstrap`, adminisztrátori (superuser vagy CREATEROLE) kapcsolattal.
-- Nem Alembic-migráció: a szerepkörök a teljes klaszterre szólnak, nem egy adatbázisra,
-- ezért egy `alembic downgrade` nem törölheti őket. A fájl idempotens, többször is futtatható.
-- A jelszavakat a parancs állítja be külön, a környezeti változókból (nem a repóból).

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('finql_owner',      false),  -- minden objektum tulajdonosa
            ('finql_migrator',   true),   -- Alembic és seed (SET ROLE finql_owner)
            ('finql_app',        true),   -- az alkalmazás: csak az app séma
            ('finql_analytics',  false),  -- az analytics nézetek tulajdonosa, RLS vonatkozik rá
            ('finql_llm_reader', true)    -- LLM-SQL: csak SELECT az analytics nézeteken
        ) AS v(role_name, can_login)
    LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r.role_name) THEN
            EXECUTE format('CREATE ROLE %I', r.role_name);
        END IF;
        -- Az attribútumokat minden futáskor újra rögzítjük, így egy kézi módosítás nem marad meg.
        EXECUTE format(
            'ALTER ROLE %I %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
            r.role_name,
            CASE WHEN r.can_login THEN 'LOGIN' ELSE 'NOLOGIN' END
        );
    END LOOP;
END
$$;

-- A migrator a tulajdonos nevében hoz létre objektumokat (SET ROLE finql_owner).
GRANT finql_owner TO finql_migrator;

-- A tulajdonos átadhatja a nézeteket a finql_analytics-nak (ALTER VIEW … OWNER TO), de a jogait
-- nem örökli (INHERIT FALSE): a két szerepkör jogosultsága nem keveredik.
GRANT finql_analytics TO finql_owner WITH INHERIT FALSE, SET TRUE;

-- Az LLM-szerepkör session-szintű korlátai. A futtató tranzakción belül szigoríthat rajtuk.
ALTER ROLE finql_llm_reader SET default_transaction_read_only = on;
ALTER ROLE finql_llm_reader SET statement_timeout = '5s';
ALTER ROLE finql_llm_reader SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE finql_llm_reader SET search_path = analytics;
-- A JIT-fordítás a rövid, interaktív lekérdezéseken többe kerül, mint amennyit hoz
-- (a small skálán egy 90 ms-os hitellekérdezésből így 400 ms lett).
ALTER ROLE finql_llm_reader SET jit = off;

-- Adatbázisszint: a finql_owner a tulajdonos, így sémát hozhat létre, és övé a public séma is
-- (PG15+: a public séma tulajdonosa a pg_database_owner). Csatlakozni csak a mi szerepköreink tudnak.
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I OWNER TO finql_owner', current_database());
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO finql_migrator, finql_app, finql_llm_reader',
        current_database()
    );
END
$$;

-- A public sémában csak az Alembic verziótáblája van; más szerepkörnek nincs ott dolga.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
