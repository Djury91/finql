-- A lekérdezésnapló csak hozzáfűzhető (append-only): az alkalmazás írhat bele és olvashatja,
-- de nem módosíthat és nem törölhet belőle. Az alapértelmezett jogokat (000_schema.sql: SELECT,
-- INSERT, UPDATE, DELETE minden új táblára) itt szűkítjük. Így egy SQL-injection vagy hibás kód
-- az alkalmazásban sem tüntetheti el a nyomokat.

REVOKE UPDATE, DELETE, TRUNCATE ON app.query_log FROM finql_app;
