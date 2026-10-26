-- Session-kontextus a sorszintű jogosultsághoz (RLS).
--
-- A futtató (executor) tranzakción belül állítja be, paraméterezve, a JWT-ből:
--   SELECT set_config('app.branch_id', $1, true), set_config('app.scope', $2, true);
-- Az LLM által generált SQL-ben a set_config és a SET tiltott (validátor, 05-ös dokumentum).
--
-- Fail-closed: kontextus nélkül branch_id() NULL, all_branches() false, vagyis 0 sor.
-- Érvénytelen branch_id (nem szám) esetén a cast hibát dob, a lekérdezés elbukik.

CREATE SCHEMA app_ctx;

CREATE FUNCTION app_ctx.branch_id() RETURNS int
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT nullif(current_setting('app.branch_id', true), '')::int
$$;

CREATE FUNCTION app_ctx.all_branches() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT coalesce(current_setting('app.scope', true), '') = 'all'
$$;

COMMENT ON FUNCTION app_ctx.branch_id() IS
    'A felhasználó fiókja (app.branch_id). NULL, ha nincs beállítva: ilyenkor a fiókhoz kötött adatból 0 sor látszik.';
COMMENT ON FUNCTION app_ctx.all_branches() IS
    'Igaz, ha a felhasználó minden fiók adatát láthatja (app.scope = ''all'', pl. központi elemző).';

-- A policy-kben hívott függvények EXECUTE jogát a lekérdezést futtató szerepkörre ellenőrzi a
-- PostgreSQL (nem a nézet tulajdonosára), ezért az LLM-szerepkörnek is kell.
REVOKE ALL ON FUNCTION app_ctx.branch_id(), app_ctx.all_branches() FROM PUBLIC;
GRANT USAGE ON SCHEMA app_ctx TO finql_analytics, finql_llm_reader;
GRANT EXECUTE ON FUNCTION app_ctx.branch_id(), app_ctx.all_branches()
    TO finql_analytics, finql_llm_reader;
