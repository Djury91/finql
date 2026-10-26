# 02 – Technológiai döntések

Ez a dokumentum két kérdést jár körül általánosan, projektmérettől függően:
**Django vagy FastAPI** és **code-first vagy DB-first**. Utána rögzíti, mit választunk
ebben a projektben és miért (döntésnapló, ADR).

---

## 1. Django vs FastAPI

### Mi a lényegi különbség?

| | **Django** | **FastAPI** |
|---|---|---|
| Filozófia | „Batteries included”: ORM, admin, auth, migrációk, formok, template-ek egyben | Minimális mag: routing, validáció (Pydantic), OpenAPI. A többit te rakod össze. |
| ORM | Django ORM, beépített migrációkkal | Nincs. Általában SQLAlchemy 2.0 + Alembic, vagy SQLModel. |
| Admin felület | Beépített, erős, ingyen van | Nincs (külső: `sqladmin`) |
| Auth | Beépített felhasználókezelés, session, jogosultságok | Saját megoldás (JWT, OAuth2-segédek) vagy külső könyvtár |
| Async | Async view-k vannak, de az ORM async API-ja nagyrészt még szálakon futó szinkron kódot csomagol | Natív async, a teljes stack (driver, HTTP-kliens) végig async lehet |
| API | DRF vagy Django Ninja kell hozzá | Az API az elsődleges cél, az OpenAPI-dokumentáció automatikus |
| Tanulási görbe | Sok konvenció, de egyszer kell megtanulni | Gyors indulás, de az architektúrát neked kell kitalálni |
| Erősség | CRUD-nehéz, admin-igényes, sok modellből álló üzleti alkalmazás | API-first, I/O-intenzív szolgáltatások: **LLM-hívások, streaming**, microservice-ek |

### Melyiket milyen méretű projekthez?

A felhasználószám **ritkán** dönt. Mindkettő jól skálázható horizontálisan (az Instagram
backendje Django-n nőtt fel). Négy szempont számít igazán:

1. **Mennyi a CRUD és az admin?** Sok domainmodell és back-office képernyő esetén a Django előnyben van.
2. **Milyen az I/O-profil?** Hosszú külső hívásoknál (LLM: 2–30 s), streamingnél és websocketnél a FastAPI.
3. **Ki birtokolja a sémát?** Ha az alkalmazás, mindkettő jó. Ha a DBA vagy egy megosztott DWH, a FastAPI + SQLAlchemy rugalmasabb.
4. **Mit ismer a csapat?** Egy jól ismert eszköz többet ér egy „jobb” ismeretlennél.

| Projektméret | Jellemzők | Ajánlott framework | Séma-megközelítés | Architektúra |
|---|---|---|---|---|
| **Prototípus / PoC**<br>1–10 felhasználó, 1 fejlesztő, hetek | Ötlet validálása, demó | **FastAPI**, ha API vagy LLM-demó; **Django**, ha azonnal kell admin és login. (Belső demóhoz akár Streamlit.) | Code-first | Egyetlen alkalmazás |
| **Kis termék**<br>10–1 000 felhasználó, 1–3 fejlesztő | CRUD + néhány AI-funkció | **Django**, ha a CRUD és az admin dominál. **FastAPI**, ha API-first, és az AI a fő érték. | Code-first | Monolit |
| **Közepes**<br>1 000–100 000 felhasználó, 3–15 fejlesztő | Több domain, háttérfeladatok, integrációk | **Django moduláris monolit** + Celery. Gyakori hibrid: **Django core + külön FastAPI AI-szolgáltatás**. | Code-first az alkalmazástáblákra, **DB-first** a megosztott és riportsémákra | Moduláris monolit, queue, cache |
| **Nagy / enterprise**<br>100 000+ felhasználó, több csapat, szabályozott környezet (bank!) | Megosztott adatbázisok, DBA-k, audit, compliance | Szolgáltatásonként: Django a back-office-ra, FastAPI a nagy átvitelű vagy async szolgáltatásokra | **DB-first** (DBA-review, Flyway / Liquibase / Sqitch) | Szolgáltatások, eseményvezérelt integráció |

**Ökölszabály LLM-es termékekhez:** ha a termék magja az LLM-integráció, és kevés a
back-office képernyő, válassz FastAPI-t. Ha egy meglévő Django-termékbe kerül AI-funkció,
maradj Django-ban (async view vagy Celery task az LLM-hívásra), és csak akkor emeld ki
egy FastAPI-szolgáltatásba, ha a terhelés vagy a streaming indokolja.

---

## 2. Code-first vs DB-first

| | **Code-first** | **DB-first** |
|---|---|---|
| Igazságforrás | Python-modellek (ORM) | SQL DDL-fájlok és maga az adatbázis |
| Migráció | Generált (Alembic autogenerate, `makemigrations`) | Kézzel írt SQL-migrációk (Alembic `op.execute`, Flyway, Sqitch, dbmate) |
| Erősség | Gyors iteráció, típusos modellek, egy nyelv | Teljes kontroll: RLS, nézetek, függvények, particionálás, triggerek, speciális indexek, `COMMENT ON` |
| Gyengeség | Az ORM nem fejez ki mindent (RLS, particionálás, policy-k). Generált SQL-meglepetések. | Duplikáció a modellek felé, a fejlesztőnek SQL-t kell írnia |
| Mikor? | Az alkalmazás birtokolja a sémát, sok gyorsan változó tábla | Megosztott vagy szabályozott adat, a DB-funkciók a megoldás részei, DBA a csapatban |

### Méret szerint

- **Kicsi:** code-first, mert a sebesség számít.
- **Közepes:** hibrid. Az alkalmazás saját táblái code-first módon, a riport-, integrációs és biztonsági réteg (nézetek, RLS, függvények) SQL-ben.
- **Nagy / szabályozott:** DB-first, review-zott SQL-migrációkkal. Az ORM-modellek követik a sémát, nem fordítva.

---

## 3. Mit választunk ebben a projektben?

### ADR-001: FastAPI (nem Django)

**Döntés:** FastAPI + SQLAlchemy 2.0 (async) + Alembic. Adatbázis-driver: **asyncpg** az async
alkalmazáskódhoz, **psycopg 3** (szinkron) az eszközökhöz (Alembic, `COPY`-alapú seed).

**Indoklás:**
- A termék magja az LLM-integráció: hosszú, I/O-kötött hívások és streamelt válasz (SSE). A natív async itt valódi előny.
- API-first: a felület csak egy vékony kliens, admin felületre alig van szükség.
- A projekt célja az SQL-tudás bemutatása. Az SQLAlchemy Core és a nyers SQL teljes kontrollt ad, az ORM nem takarja el az adatbázist.
- A Pydantic-sémák egyben az LLM strukturált kimenetének és az eszközök (tool) paramétereinek leírói is.

**Amit feladunk és hogyan pótoljuk:**
- Beépített admin → `sqladmin`, ha kell (opcionális).
- Beépített auth → saját JWT + Argon2. Kis munka, és jól mutatja, hogy értjük.

**Módosítás (2026-10-26, 0. fázis):** az eredeti terv a psycopg 3 async módja volt. Windows-on
viszont ez nem fut az alapértelmezett `ProactorEventLoop`-pal, ehhez minden belépési pontra
(uvicorn, TestClient, pytest) külön hurokbeállítás kellene. Az asyncpg minden platformon működik
és gyorsabb is. A szinkron psycopg-t ez nem érinti.

**Mikor gondolnánk újra:** ha a back-office CRUD képernyők válnának dominánssá.
Ugyanez az architektúra Django + Django Ninja + `pgvector` Django-integrációval is
felépíthető (lásd a 8. fázist).

### ADR-002: Hibrid séma-stratégia (DB-first + code-first), egy migrációs eszközzel

**Döntés:**
- A `bank` és az `analytics` séma, a szerepkörök és az RLS **DB-first**: kézzel írt SQL-fájlok a `db/` mappában, amelyeket Alembic-migrációk futtatnak le `op.execute`-tal.
- Az `app` séma (felhasználók, beszélgetések, napló, dokumentumok) **code-first**: SQLAlchemy-modellekből Alembic autogenerate, review után.

**Indoklás:**
- A banki domain a valóságban is egy meglévő, DBA-k által kezelt adatbázis lenne. Az alkalmazás csak olvassa. Ez a reális szcenárió.
- A biztonság magja (RLS, `security_barrier` nézetek, szerepkörök, `statement_timeout`) ORM-mel nem fejezhető ki tisztán.
- A `COMMENT ON TABLE/COLUMN` leírások egyben az LLM szemantikai rétegét adják: a séma dokumentációja és a prompt-kontextus ugyanaz az igazságforrás.
- Egy eszköz (Alembic) futtat mindent, így egyetlen verziósor és egyetlen `upgrade head` van.

**Szabály:** az autogenerate a `bank` és `analytics` sémát figyelmen kívül hagyja
(`include_name` szűrő az `env.py`-ban), különben törölni akarná a „nem modellezett” táblákat.

**Kiegészítés (2026-10-26, 1. fázis):** a szerepköröket nem Alembic-migráció hozza létre,
hanem egy külön, idempotens bootstrap-lépés (`finql db bootstrap`, adminisztrátori kapcsolattal).
A szerepkör klaszterszintű objektum: egy `alembic downgrade` nem törölheti, és a migrátornak
sem kell hozzá `CREATEROLE` jog. Az Alembic ezután a jogkorlátozott `finql_migrator`-ral fut,
`SET ROLE finql_owner` mellett, így minden objektum egyetlen tulajdonosé.

### ADR-003: PostgreSQL 18 + pgvector, nincs külön vektor-adatbázis

**Indoklás:** ~2 000 chunknál a pgvector HNSW-indexe bőven elég. A vektor és a relációs
adat egy helyen van, így a jogosultsági szűrés, a JOIN és a tranzakció egy SQL-ben
megoldható. A hibrid keresést (`tsvector` magyar szótárral + vektor) is egy lekérdezés
végzi. Egy kevesebb rendszer, amit üzemeltetni kell.

**Mikor gondolnánk újra:** több tízmillió vektor, vagy ha más csapat is használná
önálló szolgáltatásként.

### ADR-004: LLM-provider absztrakció, Claude az alapértelmezett

- `LLMClient` protokoll (`generate_structured` a 3. fázistól; `stream`, `tool_call` a 6. fázisban). Az implementáció cserélhető (Anthropic, helyi Ollama, mock a tesztekhez).
- Alapértelmezett modellek (környezeti változóból felülírhatók):
  - SQL-generálás és agent: `claude-sonnet-5-5`
  - Olcsó feladatok (routing, összefoglalás, címadás): `claude-haiku-5-5`
- **Embedding:** `Embedder` protokoll. Alapértelmezés a Voyage AI API (könnyű Docker-image), alternatívaként helyi `bge-m3` (többnyelvű, jól kezeli a magyart, offline is fut). Mindkettő 1024 dimenziós. A chunk mellé eltároljuk a modell nevét, mert modellváltáskor újra kell embeddingelni.
- A tesztek determinisztikus mock LLM-mel futnak. Valódi API-hívás csak az eval futásban van.

**Megvalósítás (3. fázis):**
- `generate_structured` strukturált kimenettel: a Pydantic-modellből JSON-séma megy az
  `output_config.format`-ba, így a válasz mindig a sémának megfelelő JSON. A `messages.parse()`
  helyett `create()`: a `parse()` már a `stop_reason` vizsgálata előtt validálna, és egy
  biztonsági elutasítás (`refusal`) vagy egy csonka válasz így JSON-hibaként, 500-zal jönne vissza.
  Ezt egy unit teszt fogta meg.
- Biztonsági elutasításnál a szerveroldali tartalék (`fallbacks: "default"`) automatikusan egy
  másik modellel próbálja újra; a naplóba az a modell kerül, amelyik válaszolt.
- `effort: medium` kifejezetten beállítva (Sonnet 5.5-ön az alapérték `high`), a rendszerprompt
  (szabályok + séma) prompt-cache-elve: minden kérdésnél ugyanaz.
- Az önjavító kör **új, egylépéses kérés**, amelyben benne van a hibás SQL és a hibaüzenet, nem
  egy folytatott beszélgetés. Nincs mit visszajátszani vagy szerkeszteni az előzményekben.
- API-kulcs nélkül (`FINQL_LLM_PROVIDER=fake`) az alkalmazás a projektterv példakérdéseire a kézzel
  írt SQL-lel válaszol, így a teljes biztonsági lánc kulcs és költség nélkül is kipróbálható.

### ADR-006: A költségőr fő mércéje a becsült sorszám, nem a költség

A `large` skálán (15 millió tranzakció) mérve az EXPLAIN *költsége* nem választja szét a jó és a
rossz lekérdezést: a `loans` nézetre írt példakérdés becsült költsége 16 millió, mégis 0,5 s alatt
fut, egy hibás JOIN pedig 2 millió költséggel is percekig tartana. Az ok: a tervező a fiókszintű
RLS-feltétel (`(minden fiók) OR EXISTS(…)`) mindkét ágát beárazza minden törlesztőrészletre, pedig
futáskor az InitPlan rövidre zárja.

A tervben szereplő **legnagyobb köztes sorszám** viszont éles határt húz: a legitim lekérdezéseknél
legfeljebb ~8 millió, a feltétel nélküli vagy rossz feltételű JOIN-oknál 70 milliótól 10¹⁴-ig.
Ezért: sorszám-küszöb 50 millió (fő szabály), költségküszöb 100 millió (hátvéd). A mérés részletei:
[05 – Text-to-SQL biztonság](05-text-to-sql-biztonsag.md).

### ADR-005: Fejlesztői eszközök

| Terület | Választás | Miért |
|---|---|---|
| Csomagkezelés | **uv** | Gyors, lockfile, Python-verziót is kezel |
| Lint/format | **ruff** | Egy eszköz a flake8, isort és black helyett |
| Típusok | **mypy** (strict a `src/`-re) | |
| Tesztek | **pytest**, pytest-asyncio, **testcontainers** (valódi Postgres) | Az RLS-t és a nézeteket SQLite-on nem lehet tesztelni |
| SQL-elemzés | **sqlglot** | AST-alapú validálás, Postgres-dialektus |
| CLI | **typer** | `finql seed`, `finql ingest`, `finql eval` |
| Logolás | **structlog** (JSON) | Később OpenTelemetry |
| Konfiguráció | **pydantic-settings** | `.env` + típusos beállítások |
| Feladatfuttató | **poethepoet** (`uv run poe test`) | Windows-on is megy, nem kell `make` |
| Konténer | Docker Compose (`pgvector/pgvector:pg18`) | |
| CI | GitHub Actions | lint → formázás → típus → teszt (a Postgrest a testcontainers indítja) |

---

## Döntésnapló összefoglaló

| ADR | Döntés | Státusz |
|---|---|---|
| 001 | FastAPI + SQLAlchemy 2.0 async + Alembic; asyncpg (app) + psycopg (eszközök) | Elfogadva, módosítva |
| 002 | Hibrid séma: `bank`/`analytics` DB-first, `app` code-first, mindent Alembic futtat | Elfogadva |
| 003 | PostgreSQL 18 + pgvector, nincs külön vektor-DB | Elfogadva |
| 004 | Provider-független LLM- és embedding-interfész, Claude az alapértelmezett | Elfogadva |
| 005 | uv, ruff, mypy, pytest + testcontainers, sqlglot, typer | Elfogadva |
| 006 | Költségőr: a becsült köztes sorszám a fő mérce, a költség csak hátvéd | Elfogadva (mérés alapján) |

Új döntésnél új sor kerül ide, és egy rövid ADR-szakasz a fenti formában.
