-- Az alkalmazás saját sémája (code-first: a táblákat SQLAlchemy-modellekből az Alembic
-- autogenerate hozza létre). Itt csak a séma és a jogok vannak, ezek nem modellezhetők.

CREATE SCHEMA app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO finql_app;

-- A finql_owner által ezután létrehozott táblákra és szekvenciákra a finql_app automatikusan
-- jogot kap, így egy új modellhez nem kell külön GRANT. A szigorúbb táblák (pl. az append-only
-- query_log a 3. fázisban) a saját migrációjukban vonják vissza, ami nem kell.
ALTER DEFAULT PRIVILEGES FOR ROLE finql_owner IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO finql_app;
ALTER DEFAULT PRIVILEGES FOR ROLE finql_owner IN SCHEMA app
    GRANT USAGE, SELECT ON SEQUENCES TO finql_app;

COMMENT ON SCHEMA app IS 'FinQL alkalmazásadatok: felhasználók, beszélgetések, napló, dokumentumok.';
