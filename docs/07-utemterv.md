# 07 – Ütemterv lépésről lépésre

Minden fázis végén működő, tesztelt, `main`-be mergelt állapot van. Az időbecslés heti ~10 óra mellékállású munkára szól.

| Fázis | Téma | Becslés | Fókusz |
|---|---|---|---|
| 0 | Repó és eszközök | 2–3 nap | Professzionális projektalapok, CI |
| 1 | Banki adatbázis (DB-first) + seed | 1,5 hét | Haladó PostgreSQL: particionálás, RLS, szerepkörök, `COPY`-alapú adatgenerálás |
| 2 | FastAPI-gerinc + auth | 1 hét | Async backend, SQLAlchemy 2.0, Alembic, JWT, tesztek valódi DB-vel |
| 3 | Text-to-SQL v1 | 1,5 hét | LLM-integráció, többrétegű SQL-biztonság, audit |
| 4 | Eval + few-shot | 1 hét | Mérhető AI-minőség, regressziótesztelés |
| 5 | RAG | 1,5 hét | pgvector, hibrid keresés, inkrementális pipeline |
| 6 | Agent + streaming | 1,5 hét | Tool-use, beszélgetés-memória, SSE |
| 7 | UI, telepítés, demó | 1 hét | Végponttól végpontig működő termék |
| 8 | Haladó (opcionális) | – | Megfigyelhetőség, MCP, hash-láncolt audit |

---

## 0. fázis – Repó és eszközök

**Cél:** üres, de professzionális váz, zöld CI-jal.

- [x] `git init`, GitHub-repó létrehozása (`finql`), MIT-licenc
- [x] uv-projekt, Python 3.12, `src/finql` layout, `finql` CLI-belépési pont
- [x] Függőségek: `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `pydantic-settings`, `typer`; dev: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `httpx2`, `testcontainers`, `pre-commit`, `poethepoet`. (Az `alembic`, a `psycopg` és a `structlog` akkor kerül be, amikor használjuk: 1. és 2. fázis.)
- [x] `docker-compose.yml` a `pgvector/pgvector:pg18` image-dzsel, healthcheckkel és volume-mal
- [x] `.env.example`, `core/config.py`
- [x] `/health` és `/ready` végpont (a `/ready` a DB-t is pingeli), unit- és integrációs teszt
- [x] `pre-commit`: ruff, ruff-format, mypy, alap-hookok, valamint egy őr, amely nem engedi commitolni a `private/` mappát
- [x] GitHub Actions: `ci.yml` (lint, formázás, mypy, pytest testcontainersszel)

**Kész, ha:** `uv run poe check` lokálisan és a CI-ban is zöld.

**Tanulságok (Windows):** a psycopg async módja nem fut a `ProactorEventLoop`-pal (→ asyncpg, ADR-001).
A `localhost` IPv6-ra oldódik fel, és ~2 s késést okoz (→ `127.0.0.1` a DSN-ben). A testcontainers
Ryuk-konténere Docker Desktopon nem indul el időben (→ Windows-on kikapcsolva, a CI-ban bekapcsolva).

---

## 1. fázis – Banki adatbázis (DB-first) és szintetikus adatok

**Cél:** egy valószerű, jogosultságkezelt, dokumentált banki adatbázis.

- [x] `db/roles`: a szerepkörök, alapjogok, `REVOKE … FROM PUBLIC` (`finql db bootstrap`, nem Alembic: a szerepkör klaszterszintű)
- [x] `db/bank`: típusok, táblák, FK-k, CHECK-ek, havi particionálás a `transactions` táblán
- [x] Alembic-migrációk, amelyek az SQL-fájlokat futtatják. `env.py`: `SET ROLE finql_owner`, `include_name` szűrő.
- [x] `pipelines/seed`: Faker `hu_HU`, skálák (`tiny`/`small`/`large`), rögzített seed, beépített „történetek”
- [x] Betöltés `COPY`-val, indexek a betöltés után, `ANALYZE` (`small`: ~55 s)
- [x] `db/analytics`: nézetek PII nélkül, `amount_huf`, `dpd_bucket`, materializált havi összesítő (fiókra szűrő nézet mögött)
- [x] `COMMENT ON` minden nézetre és oszlopra (ebből lesz az LLM-kontextus)
- [x] `db/security`: `app_ctx` függvények, RLS policy-k, nézettulajdonos `finql_analytics`
- [x] Integrációs tesztek: RLS (saját fiók, összes fiók, kontextus nélkül 0 sor), read-only, PII-hozzáférés tiltva
- [x] A projektterv példakérdései kézzel írt SQL-lel, az LLM-szerepkörrel futtatva (`small`: mind 200 ms alatt)

Két PR-ban: (1) séma, szerepkörök, seed; (2) nézetek, RLS, biztonsági tesztek.

**Kész, ha:** `uv run finql seed --scale small` 5 percen belül lefut, és a biztonsági
integrációs tesztek zöldek. Kézzel írt SQL-lel megválaszolható a [projektterv](01-projekt-terv.md)
összes példakérdése. Ezekből lesznek az arany SQL-ek.

---

## 2. fázis – FastAPI-gerinc és auth

**Cél:** az alkalmazás váza, felhasználókkal és szerepkörökkel.

- [x] `main.py` app factory, `lifespan`-ben két engine (`app` és `llm`)
- [x] `core/db.py`: async session dependency, tranzakciókezelés (kérésenként egy tranzakció)
- [x] `auth`: `User` modell (code-first), Alembic autogenerate, review; `alembic check` teszt a modell–migráció eltérésre
- [x] Argon2id jelszó-hash (threadpoolban), JWT kiadás és ellenőrzés, `get_current_user`, `require_role`
- [x] `finql user create` CLI-parancs (rejtett jelszóbekérés), `finql user demo`: demófelhasználók szerepkörönként
- [x] Egységes hibaformátum (`core/errors.py`), request-ID middleware, structlog
- [x] Tesztek: bejelentkezés, lejárt token, rossz szerepkör → 403, letiltott felhasználó, hamisított token

**Kész, ha:** a `/docs`-ban (OpenAPI) be lehet jelentkezni, és a `/auth/me` a helyes szerepkört adja.

---

## 3. fázis – Text-to-SQL v1

**Cél:** a fő funkció, a teljes biztonsági lánccal.

- [x] `llm/client.py` protokoll, `anthropic_client.py`, `fake_client.py`
- [x] `llm/usage.py`: tokenek, késleltetés, napi keret ellenőrzése
- [x] `schema_context.py`: katalógus betöltése az `analytics` sémából, cache, kompakt szöveges formátum
- [x] `prompts/text_to_sql.v1.md`: szerep, szabályok, séma, példák, kimeneti séma
- [x] `generator.py`: strukturált kimenet (`sql`, `explanation`, `assumptions`)
- [x] `validator.py`: a [biztonsági dokumentum](05-text-to-sql-biztonsag.md) összes szabálya, és 79 rosszindulatú tesztminta
- [x] `cost_guard.py`: EXPLAIN-küszöb (a `large` skálán kalibrálva, ADR-006)
- [x] `executor.py`: `BEGIN READ ONLY`, `set_config(…, true)`, sorlimit, időmérés
- [x] Önjavító ciklus SQL-hibára (max. 2 kör), tiltott szándéknál nincs újrapróbálás
- [x] `audit`: `QueryLog` modell, append-only jogok, naplózás minden ágon
- [x] Végpontok: `POST /query`, `GET /query/history`, `GET /schema`, `GET /audit/queries`

**Kész, ha:** a példakérdések többsége helyes választ ad, az elutasítandók elutasítva,
és minden kísérlet megjelenik a `query_log` táblában.

**Állapot:** a lánc ál-LLM-mel végig tesztelt (elutasítás, önjavítás, költségőr, időkorlát,
tokenkeret, napló). A valódi Claude-dal futó ellenőrzés (`uv run poe test-llm`) API-kulcsra vár;
a rendszeres mérés a 4. fázis evalja.

**Tanulságok:**
- Az EXPLAIN-költség az RLS miatt félrevezető (a hitelnézet: 16 millió költség, 0,3 s). A becsült
  köztes sorszám választja szét a jó és a rossz lekérdezést (ADR-006). Mérés nélkül rossz küszöb lett volna.
- Az SDK `parse()` a `stop_reason` előtt validál: egy refúzió 500-as hibát okozott volna.
  API-kulcs nélkül pedig `TypeError` jön, nem SDK-hiba. Az elsőt egy mockolt HTTP-teszt fogta meg,
  a másodikat egy kézi próba; most mindkettőre van teszt.
- Az írási kísérletek nagy része már az EXPLAIN-nél elbukik (nem frissíthető nézet), ezért a
  read-only réteget egyszerű, frissíthető nézetekkel kell tesztelni, különben a teszt rossz okból zöld.
- A naplót külön tranzakcióban kell írni: az elutasítás hibaválasza visszagörgetné.

## 4. fázis – Eval és dinamikus few-shot

**Cél:** a minőség számokkal mérhető, és a változtatások hatása látható.

- [x] `eval/datasets/golden.yaml`: 50 kérdés (16 könnyű, 23 közepes, 11 nehéz; címkék: join, idő, window, aggregáció és társaik), elvárt SQL, szerepkör (4 fiókvezetői kérdés)
- [x] `eval/datasets/adversarial.yaml`: 20 elutasítandó kérdés, hét kategóriában
- [x] `eval/runner.py`: elvárt és generált SQL futtatása, eredményhalmazok összevetése (sorrend csak rangsornál számít; numerikus tolerancia; oszlopok érték szerint, ADR-007)
- [x] Metrikák: végrehajtási pontosság, érvényes SQL aránya, elutasítási arány, p50/p95 késleltetés, tokenek kérdésenként
- [x] Eredmények az `eval_runs`/`eval_results` táblákba, markdown-riport, két futás összevetése (`finql eval compare`)
- [x] `app.sql_examples` + embedding (Voyage, `voyage-4`): a 3 leghasonlóbb példa dinamikusan kerül a promptba (`finql examples sync`, 28 példa)
- [ ] Összevetés: v1 prompt few-shot nélkül vs. dinamikus few-shottal → eredmény a README-be (API-kulcsra vár)
- [x] `eval.yml` workflow (kézi indítás, API-kulcs secretből)

**Kész, ha:** legalább 80% pontosság az arany soron, 100% elutasítás a rosszindulatú soron,
és a riport bekerült a repóba.

**Állapot:** a harness kész és tesztelt. Az orákulummal (az elvárt SQL-t visszaadó ál-LLM) a
`small` skálán 50/50 és 20/20, vagyis a kérdéssorok, a hatókörök, az összevetés, a tárolás és a
riport rendben van. A valódi mérés API-kulcsra vár: `FINQL_ANTHROPIC_API_KEY`, few-shothoz
`FINQL_VOYAGE_API_KEY` is.

**Tanulságok:**
- A kérdéssor megírása két korábbi hibát hozott elő, még mielőtt egy modell válaszolt volna.
  (1) Az LLM-szerepkör UTC-ben futott, így a `booked_at >= '2025-09-01'` két órával később
  kezdte a hónapot, mint a `booked_date` és a havi összesítő, és a szomszédos partíciót is olvasta.
  Javítás: `ALTER ROLE … SET timezone = 'Europe/Budapest'`. (2) A seedben a devizaszámláknak
  nem volt kártyájuk, így a külföldi kereskedőknek egyetlen tranzakciójuk sem volt.
- Kis adaton a rossz válasz is lehet „helyes”: a `tiny` skálán a 30 és a 90 napon túl késő
  hitelek száma ugyanannyi, így egy rossz szűrő is átment. A mérés ezért a `small` skálán fut, a
  `tiny` csak a harness tesztjeire való.
- Egy arany kérdésnek egy helyes válasza legyen. A „top kereskedők kategóriánként” kétértelmű
  volt, mert a kereskedőnevek nem egyediek (egy név több üzlet), így név és azonosító szerint mást
  adott; a kérdés kategóriákra változott. A rangsorok határán nincs holtverseny (ellenőrizve).
- A few-shot példák a felhasználói üzenetbe kerülnek: a rendszerprompt így bájtra ugyanaz
  marad, és cache-elhető (ADR-007).

---

## 5. fázis – RAG

**Cél:** a belső szabályzatokból forrásmegjelölt válaszok.

- [x] 20 szintetikus banki dokumentum (`data/documents/`, 15 általános, 5 belső): díjjegyzékek, kamathirdetmény, termékfeltételek, követeléskezelés, panaszkezelés, pénzmosás-megelőzés, hitelezési szabályzat, értékvesztés, fogalomtár
- [x] `Document` és `DocumentChunk` modell, HNSW- és GIN-index, generált `tsvector` (`hungarian`, a címsor nagyobb súllyal)
- [x] `chunking.py`: címsor-alapú darabolás, ~500 token, átfedéssel, a szakaszcím a részlet mellett
- [x] `llm/embeddings.py`: Voyage és helyi (hash-alapú) implementáció, batch-elés (a 4. fázisból)
- [x] `finql ingest`: hash-alapú inkrementális betöltés egy tranzakcióban, modellváltáskor újra-embedding, törölt fájlok kezelése
- [x] `retriever.py`: hibrid keresés RRF-fel, olvasási szint az SQL-ben (`min_role` helyett, ADR-008); embedding nélkül csak szöveges keresés
- [x] `POST /documents/search` és `POST /documents/answer`: válasz idézetekkel (dokumentum + szakasz), hivatkozás nélküli választ nem ad; `answer_log` (append-only, a tokenkeretbe számít)
- [x] Mini eval: 20 kérdés → az elvárt dokumentum a top 5-ben van? (`finql eval retrieval`: recall@5, MRR, szivárgás)
- [ ] Élő próba Claude-dal és Voyage-dzsal: recall@5 a valódi embeddinggel, idézett válaszok (API-kulcsra vár)

**Kész, ha:** „Mennyi a késedelmi kamat?” jellegű kérdésekre helyes, idézett válasz jön,
és a jogosultság nélküli dokumentum nem jelenik meg.

**Állapot:** a teljes út kész és tesztelt: betöltés, hibrid keresés, olvasási szint, idézett
válasz, napló. A kulcs nélküli (hash-alapú) embeddinggel a keresési eval **recall@5 = 17/17**,
MRR 0,75, és a három szivárgáspróbán egyetlen belső dokumentum sem jutott fiókvezetőhöz. A
válasz útja ál-LLM-mel tesztelt (idézet-ellenőrzés, napló, tokenkeret). A Voyage-dzsal mért
recall és a Claude-dal adott válaszok API-kulcsra várnak.

**Tanulságok:**
- A szerepkörök nem létra: az auditor nem lát banki adatot, mégis minden szabályzatot olvas. A
  dokumentum ezért olvasási szintet kap, és a szerepkörhöz kódban rendelünk szintet, nem
  „legalább ez a szerepkör” szabályt.
- A `plainto_tsquery` `AND`-del köti a szavakat: egy természetes kérdésre („Mit kell tennie a
  fiókvezetőnek, ha…”) szinte semmit nem talál. A szavakat `OR`-ral kötjük, a rangsort a
  `ts_rank_cd` adja.
- A hivatkozás nélküli választ a kód dobja el, nem a promptra bízzuk: a prompt kéri, a kód
  ellenőrzi. Ugyanez a minta, mint a text-to-SQL-nél (a modell javasol, a kód dönt).
- A naplóban a forrás `fájl@verzió#részlet`, nem részletazonosító: egy újratöltés után is
  megmondja, melyik szövegváltozatra épült a válasz.

---

## 6. fázis – Agent és streaming

**Cél:** egy beszélgetésben SQL és dokumentum együtt, valós idejű válasszal.

- [ ] `Conversation`, `Message` modellek
- [ ] `agent/tools.py`: `query_database`, `search_documents`, `describe_schema`, `get_metric_definition`, mindegyik Pydantic-sémával
- [ ] Tool-use ciklus: max. 6 hívás, tokenkeret, időkorlát, hibakezelés eszközönként
- [ ] Beszélgetés-memória: az utolsó N üzenet, hosszabb beszélgetésnél összefoglaló (Haiku)
- [ ] SSE-stream: szövegdarabok és eszközhívás-események (`tool_start`, `tool_result`)
- [ ] Indirekt prompt injection teszt: mérgezett dokumentum, az agent nem követi
- [ ] Vegyes eval-kérdések (SQL + dokumentum)

**Kész, ha:** „Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?”
egy válaszban, számmal és idézettel érkezik, streamelve.

---

## 7. fázis – UI, telepítés, demó

- [ ] Minimális webes felület: chat, SQL megjelenítése, eredménytábla, forrás-idézetek. (Javaslat: HTMX + Jinja a FastAPI-ból, vagy egy külön Streamlit-kliens.)
- [ ] `Dockerfile` (többlépcsős, nem-root), `docker compose up` egy paranccsal
- [ ] Telepítés egy PaaS-ra (pl. Fly.io, Railway vagy Render) menedzselt Postgresszel, ahol elérhető a pgvector
- [ ] Demó GIF/videó, architektúraábra, eval-eredmények a README-ben
- [ ] „Tanulságok” szakasz a README-ben

---

## 8. fázis – Haladó (válogatható)

- [ ] OpenTelemetry-trace (FastAPI → LLM → DB), vagy Langfuse az LLM-hívásokhoz
- [ ] Hash-láncolt `query_log` (`prev_hash`, `row_hash`): a naplóból törölt vagy módosított sor kimutatható
- [ ] MCP-szerver: a `query_database` és a `search_documents` eszköz MCP-n keresztül, így Claude Desktopból is használható
- [ ] Szemantikus válasz-cache (hasonló kérdés + ugyanaz a szerepkör → cache-elt SQL)
- [ ] Materializált nézetek frissítése ütemezve, adatfrissességi metaadat a válaszban
- [ ] Django + Django Ninja változat egy moduljáról, összehasonlító jegyzettel
