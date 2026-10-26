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

- [ ] `db/roles`: a négy szerepkör, alapjogok, `REVOKE … FROM PUBLIC`
- [ ] `db/bank`: típusok, táblák, FK-k, CHECK-ek, havi particionálás a `transactions` táblán
- [ ] Alembic-migrációk, amelyek az SQL-fájlokat futtatják. `env.py` `include_object` szűrő.
- [ ] `pipelines/seed`: Faker `hu_HU`, skálák (`tiny`/`small`/`large`), rögzített seed, beépített „történetek”
- [ ] Betöltés `COPY`-val, indexek a betöltés után, `ANALYZE`
- [ ] `db/analytics`: nézetek PII nélkül, `amount_huf`, `dpd_bucket`, materializált havi összesítő
- [ ] `COMMENT ON` minden nézetre és oszlopra (ebből lesz az LLM-kontextus)
- [ ] `db/security`: `app_ctx` függvények, RLS policy-k, nézettulajdonos `finql_analytics`
- [ ] Integrációs tesztek: RLS (saját fiók, összes fiók, kontextus nélkül 0 sor), read-only, PII-hozzáférés tiltva

**Kész, ha:** `uv run finql seed --scale small` 5 percen belül lefut, és a biztonsági
integrációs tesztek zöldek. Kézzel írt SQL-lel megválaszolható a [projektterv](01-projekt-terv.md)
összes példakérdése. Ezekből lesznek az arany SQL-ek.

---

## 2. fázis – FastAPI-gerinc és auth

**Cél:** az alkalmazás váza, felhasználókkal és szerepkörökkel.

- [ ] `main.py` app factory, `lifespan`-ben két engine (`app` és `llm`)
- [ ] `core/db.py`: async session dependency, tranzakciókezelés
- [ ] `auth`: `User` modell (code-first), Alembic autogenerate, review
- [ ] Argon2 jelszó-hash, JWT kiadás és ellenőrzés, `get_current_user`, `require_role`
- [ ] `finql create-user` CLI-parancs, demófelhasználók szerepkörönként
- [ ] Egységes hibaformátum (`core/errors.py`), request-ID middleware, structlog
- [ ] Tesztek: bejelentkezés, lejárt token, rossz szerepkör → 403

**Kész, ha:** a `/docs`-ban (OpenAPI) be lehet jelentkezni, és a `/auth/me` a helyes szerepkört adja.

---

## 3. fázis – Text-to-SQL v1

**Cél:** a fő funkció, a teljes biztonsági lánccal.

- [ ] `llm/client.py` protokoll, `anthropic_client.py`, `fake_client.py`
- [ ] `llm/usage.py`: tokenek, késleltetés, napi keret ellenőrzése
- [ ] `schema_context.py`: katalógus betöltése az `analytics` sémából, cache, kompakt szöveges formátum
- [ ] `prompts/text_to_sql.v1.md`: szerep, szabályok, séma, példák, kimeneti séma
- [ ] `generator.py`: strukturált kimenet (`sql`, `explanation`, `assumptions`)
- [ ] `validator.py`: a [biztonsági dokumentum](05-text-to-sql-biztonsag.md) összes szabálya, és legalább 50 rosszindulatú tesztminta
- [ ] `cost_guard.py`: EXPLAIN-küszöb (a `large` skálán kalibrálva)
- [ ] `executor.py`: `BEGIN READ ONLY`, `set_config(…, true)`, sorlimit, időmérés
- [ ] Önjavító ciklus SQL-hibára (max. 2 kör)
- [ ] `audit`: `QueryLog` modell, append-only jogok, naplózás minden ágon
- [ ] Végpontok: `POST /query`, `GET /query/history`, `GET /schema`, `GET /audit/queries`

**Kész, ha:** a példakérdések többsége helyes választ ad, az elutasítandók elutasítva,
és minden kísérlet megjelenik a `query_log` táblában.

---

## 4. fázis – Eval és dinamikus few-shot

**Cél:** a minőség számokkal mérhető, és a változtatások hatása látható.

- [ ] `eval/datasets/golden.yaml`: 50 kérdés (könnyű, közepes, nehéz; címkék: join, idő, window, aggregáció), elvárt SQL, szerepkör
- [ ] `eval/datasets/adversarial.yaml`: 20 elutasítandó kérdés
- [ ] `runner.py`: elvárt és generált SQL futtatása, eredményhalmazok összevetése (sorrend-érzéketlen, ha nincs ORDER BY; numerikus tolerancia)
- [ ] Metrikák: végrehajtási pontosság, érvényes SQL aránya, elutasítási arány, p50/p95 késleltetés, tokenek kérdésenként
- [ ] Eredmények az `eval_runs`/`eval_results` táblákba, markdown-riport
- [ ] `app.sql_examples` + embedding: a 3 leghasonlóbb példa dinamikusan kerül a promptba
- [ ] Összevetés: v1 prompt few-shot nélkül vs. dinamikus few-shottal → eredmény a README-be
- [ ] `eval.yml` workflow (kézi indítás, API-kulcs secretből)

**Kész, ha:** legalább 80% pontosság az arany soron, 100% elutasítás a rosszindulatú soron,
és a riport bekerült a repóba.

---

## 5. fázis – RAG

**Cél:** a belső szabályzatokból forrásmegjelölt válaszok.

- [ ] 15–20 szintetikus banki dokumentum (`data/documents/`): díjjegyzék, hitelezési szabályzat, behajtás, kártyafeltételek
- [ ] `Document` és `DocumentChunk` modell, HNSW- és GIN-index, generált `tsvector` (`hungarian`)
- [ ] `chunking.py`: címsor-alapú darabolás, ~500 token, átfedéssel, metaadat (szakaszcím)
- [ ] `llm/embeddings.py`: Voyage és helyi implementáció, batch-elés
- [ ] `finql ingest`: hash-alapú inkrementális betöltés, törölt fájlok kezelése
- [ ] `retriever.py`: hibrid keresés RRF-fel, `min_role` szűrés SQL-ben
- [ ] `POST /documents/search` és RAG-válasz idézetekkel (dokumentum + szakasz)
- [ ] Mini eval: 20 kérdés → az elvárt dokumentum a top 5-ben van? (recall@5)

**Kész, ha:** „Mennyi a késedelmi kamat?” jellegű kérdésekre helyes, idézett válasz jön,
és a jogosultság nélküli dokumentum nem jelenik meg.

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
