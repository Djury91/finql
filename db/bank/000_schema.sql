-- A banki domain nyers táblái. Az alkalmazás és az LLM sosem olvassa közvetlenül:
-- egyedül a finql_analytics fér hozzá, az analytics nézeteken keresztül (090_grants.sql).
CREATE SCHEMA bank;
REVOKE ALL ON SCHEMA bank FROM PUBLIC;

COMMENT ON SCHEMA bank IS
    'Minta Bank Zrt. – szintetikus banki adatok (ügyfelek, számlák, tranzakciók, hitelek). Személyes adatot tartalmaz.';
