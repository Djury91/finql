-- Minden analytics nézet a finql_analytics-é (RLS érvényes rá), az LLM-szerepkör csak olvashatja őket.
--
-- Ez fut utoljára: a finql_owner szándékosan nem örökli a finql_analytics jogait (INHERIT FALSE),
-- így a tulajdonosváltás után már nem írhatna leírást (COMMENT ON) és nem adhatna jogot a
-- nézetekre. A már kiadott jogok a tulajdonossal együtt átszállnak.

GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO finql_llm_reader;

-- Ciklussal, hogy egy új nézet se maradhasson ki.
DO $$
DECLARE
    v record;
BEGIN
    FOR v IN
        SELECT c.relname FROM pg_class c
        WHERE c.relnamespace = 'analytics'::regnamespace AND c.relkind = 'v'
    LOOP
        EXECUTE format('ALTER VIEW analytics.%I OWNER TO finql_analytics', v.relname);
    END LOOP;
END
$$;
