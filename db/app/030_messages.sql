-- Az agent-beszélgetések üzenetei is csak hozzáfűzhetők, mint a naplók (010_query_log.sql): egy
-- beszélgetés bizonyíték arra, mit kérdezett a felhasználó, és mit csinált az agent (melyik
-- eszközt milyen bemenettel hívta). A beszélgetés címe és ideje (conversations) módosítható.

REVOKE UPDATE, DELETE, TRUNCATE ON app.messages FROM finql_app;
