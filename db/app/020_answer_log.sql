-- A dokumentum-válaszok naplója is csak hozzáfűzhető, mint a lekérdezésnapló (010_query_log.sql):
-- az alkalmazás írhat bele és olvashatja, de nem módosíthat és nem törölhet belőle.

REVOKE UPDATE, DELETE, TRUNCATE ON app.answer_log FROM finql_app;
