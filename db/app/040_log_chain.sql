-- Hash-láncolt naplók (8. fázis): a query_log és az answer_log minden sora a saját tartalmának
-- és az előző sor hash-ének SHA-256-ja. Ha valaki utólag módosít, töröl vagy beszúr egy sort,
-- a lánc attól a ponttól nem ellenőrizhető vissza.
--
-- Az append-only jog (010_query_log.sql, 020_answer_log.sql) az alkalmazást tartja vissza. A lánc
-- azt mutatja ki, ha valaki nagyobb joggal (tulajdonos, superuser) mégis belenyúlt. Aki a teljes
-- láncot újraszámolja, az ellen a lánc feje véd: ha a fejet (sorszám + hash) rendszeresen máshol
-- is rögzítjük, az újraírt lánc feje már nem egyezik vele (docs/05, 8.).
--
-- A hash-t az adatbázis számolja triggerben, nem az alkalmazás: egy hibás vagy megkerült
-- alkalmazáskód sem írhat be rossz láncot.

-- Egy sor hash-e: a sor JSON-alakja (a row_hash kulcs nélkül, de a prev_hash-sel és a
-- sorszámmal együtt). A jsonb szöveges alakja determinisztikus (rendezett kulcsok). A NULL
-- értékű kulcsok kimaradnak: egy később hozzáadott, NULL-os oszlop így nem változtatja meg a
-- régi sorok hash-ét. Ha egy érték NULL-ra vagy NULL-ról változik, az kiderül (a kulcs eltűnik
-- vagy megjelenik).
CREATE FUNCTION app.log_row_hash(row_data jsonb) RETURNS bytea
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    RETURN sha256(convert_to(jsonb_strip_nulls(row_data - 'row_hash')::text, 'UTF8'));

-- A sor → jsonb átalakítás a session beállításaitól függ: az időbélyeg a TimeZone, a float az
-- extra_float_digits, a bytea a bytea_output szerint kerül szöveggé. Ezért minden függvény, amely
-- sort alakít jsonb-vé, rögzíti ezeket; különben ugyanaz a sor más hash-t adna egy másik
-- időzónájú sessionben.

-- A lánc következő eleme. Az advisory lock a tranzakció végéig sorba állítja az írókat
-- (a naplót saját, rövid tranzakció írja), így két egyidejű sor nem kapcsolódhat ugyanahhoz az
-- előzőhöz. Ha mégis, a chain_seq egyedi indexe elutasítja: a lánc nem ágazhat el csendben.
CREATE FUNCTION app.chain_log_row() RETURNS trigger
    LANGUAGE plpgsql
    SET TimeZone = 'UTC'
    SET extra_float_digits = 1
    SET bytea_output = 'hex'
AS $$
DECLARE
    last_seq bigint;
    last_hash bytea;
BEGIN
    -- Két egészes kulcstér: nem ütközhet az egy bigint kulcsú zárakkal (agent, 409).
    PERFORM pg_advisory_xact_lock(8, hashtext(TG_TABLE_NAME));
    EXECUTE format('SELECT chain_seq, row_hash FROM %I.%I ORDER BY chain_seq DESC LIMIT 1',
                   TG_TABLE_SCHEMA, TG_TABLE_NAME)
        INTO last_seq, last_hash;

    -- Az alkalmazás által megadott értékek felülíródnak: a láncot csak ez a függvény építi.
    NEW.chain_seq := coalesce(last_seq, 0) + 1;
    NEW.prev_hash := coalesce(last_hash, '\x0000000000000000000000000000000000000000000000000000000000000000'::bytea);
    NEW.row_hash := NULL;
    NEW.row_hash := app.log_row_hash(to_jsonb(NEW));
    RETURN NEW;
END
$$;

-- A lánc ellenőrzése sorszám szerint. Az első hibát adja vissza, és a lánc fejét:
--   gap      hiányzó sorszám: egy sort töröltek
--   link     a prev_hash nem az előző sor hash-e: sort szúrtak be vagy cseréltek
--   content  a sor tartalma nem egyezik a hash-ével: a sort módosították
-- A meghívó jogaival fut: csak azt ellenőrizheti, amit olvashat is.
CREATE FUNCTION app.verify_log_chain(log regclass)
    RETURNS TABLE (checked bigint, broken_at bigint, problem text, head_seq bigint, head_hash text)
    LANGUAGE plpgsql STABLE
    SET TimeZone = 'UTC'
    SET extra_float_digits = 1
    SET bytea_output = 'hex'
AS $$
DECLARE
    r record;
    expected_prev bytea := '\x0000000000000000000000000000000000000000000000000000000000000000';
BEGIN
    checked := 0;
    FOR r IN EXECUTE format(
        'SELECT to_jsonb(t) AS data, t.chain_seq, t.prev_hash, t.row_hash FROM %s t ORDER BY t.chain_seq',
        log)
    LOOP
        IF r.chain_seq <> checked + 1 THEN
            broken_at := checked + 1;
            problem := 'gap';
        ELSIF r.prev_hash <> expected_prev THEN
            broken_at := r.chain_seq;
            problem := 'link';
        ELSIF app.log_row_hash(r.data) <> r.row_hash THEN
            broken_at := r.chain_seq;
            problem := 'content';
        END IF;
        EXIT WHEN problem IS NOT NULL;
        checked := checked + 1;
        expected_prev := r.row_hash;
        head_seq := r.chain_seq;
        head_hash := encode(r.row_hash, 'hex');
    END LOOP;
    RETURN NEXT;
END
$$;

-- A meglévő sorok láncba fűzése, azonosító szerint. A migráció végén törlődik: ne maradjon az
-- adatbázisban egy kész „lánc-újraíró”.
CREATE FUNCTION app.chain_existing_rows(log regclass) RETURNS void
    LANGUAGE plpgsql
    SET TimeZone = 'UTC'
    SET extra_float_digits = 1
    SET bytea_output = 'hex'
AS $$
DECLARE
    r record;
    seq bigint := 0;
    prev bytea := '\x0000000000000000000000000000000000000000000000000000000000000000';
    data jsonb;
BEGIN
    FOR r IN EXECUTE format('SELECT * FROM %s ORDER BY id', log) LOOP
        seq := seq + 1;
        data := to_jsonb(r) || jsonb_build_object(
            'chain_seq', seq, 'prev_hash', '\x' || encode(prev, 'hex'), 'row_hash', NULL);
        EXECUTE format('UPDATE %s SET chain_seq = $1, prev_hash = $2, row_hash = $3 WHERE id = $4', log)
            USING seq, prev, app.log_row_hash(data), r.id;
        prev := app.log_row_hash(data);
    END LOOP;
END
$$;

SELECT app.chain_existing_rows('app.query_log');
SELECT app.chain_existing_rows('app.answer_log');
DROP FUNCTION app.chain_existing_rows(regclass);

ALTER TABLE app.query_log
    ALTER COLUMN chain_seq SET NOT NULL,
    ALTER COLUMN prev_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;
ALTER TABLE app.answer_log
    ALTER COLUMN chain_seq SET NOT NULL,
    ALTER COLUMN prev_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

CREATE TRIGGER chain_row BEFORE INSERT ON app.query_log
    FOR EACH ROW EXECUTE FUNCTION app.chain_log_row();
CREATE TRIGGER chain_row BEFORE INSERT ON app.answer_log
    FOR EACH ROW EXECUTE FUNCTION app.chain_log_row();

-- A trigger az alkalmazás jogaival fut, így annak kell a hash-függvény; az ellenőrzést az
-- auditor-végpont hívja (GET /audit/chain).
REVOKE ALL ON FUNCTION app.log_row_hash(jsonb), app.chain_log_row(),
    app.verify_log_chain(regclass) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.log_row_hash(jsonb), app.verify_log_chain(regclass) TO finql_app;
