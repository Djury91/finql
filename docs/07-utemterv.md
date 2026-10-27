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
- [x] `validator.py`: a [biztonsági dokumentum](05-text-to-sql-biztonsag.md) összes szabálya, és 80 rosszindulatú tesztminta
- [x] `cost_guard.py`: EXPLAIN-küszöb (a `large` skálán kalibrálva, ADR-006)
- [x] `executor.py`: `BEGIN READ ONLY`, `set_config(…, true)`, sorlimit, időmérés
- [x] Önjavító ciklus SQL-hibára (max. 2 kör), tiltott szándéknál nincs újrapróbálás
- [x] `audit`: `QueryLog` modell, append-only jogok, naplózás minden ágon
- [x] Végpontok: `POST /query`, `GET /query/history`, `GET /schema`, `GET /audit/queries`

**Kész, ha:** a példakérdések többsége helyes választ ad, az elutasítandók elutasítva,
és minden kísérlet megjelenik a `query_log` táblában.

**Állapot:** a lánc ál-LLM-mel végig tesztelt (elutasítás, önjavítás, költségőr, időkorlát,
tokenkeret, napló). A valódi Claude-dal (`uv run poe test-llm`, 2026-10-27) a példakérdések
helyes választ adnak, a fiókvezetői kérdés a fiókban marad, és a három rosszindulatú kérdés nem
hoz vissza adatot. A rendszeres mérés a 4. fázis evalja.

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
- [x] Összevetés: v1 prompt few-shot nélkül vs. dinamikus few-shottal → eredmény a README-be
- [x] `eval.yml` workflow (kézi indítás, API-kulcs secretből)

**Kész, ha:** legalább 80% pontosság az arany soron, 100% elutasítás a rosszindulatú soron,
és a riport bekerült a repóba.

**Állapot:** a harness kész és tesztelt. Az orákulummal (az elvárt SQL-t visszaadó ál-LLM) a
`small` skálán 50/50 és 20/20, vagyis a kérdéssorok, a hatókörök, az összevetés, a tárolás és a
riport rendben van. A valódi mérés (2026-10-27, Claude Sonnet 5.5, `voyage-4`): a pontosított
arany soron **49/50 (98%)** 3 példával és 48/50 (96%) nélküle, **20/20** elutasítás, 100% érvényes
SQL, p50 3,2 s. A riportok: `eval/reports/published/`.

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
- Az első valódi mérés hibáinak fele a kérdéssor hibája volt: két kérdés kétértelmű
  („legjobban nőtt”: abszolút vagy százalékos; „prémium és lakossági”: együtt vagy
  szegmensenként). A hibás válaszokat ezért egyenként kell elolvasni, mielőtt a promptot
  javítjuk. A pontosítás után a modell few-shot nélkül is helyesen felelt rájuk.
- A kérdést csak addig szabad pontosítani, amíg egy helyes válasza van; utána a modell hibája
  marad hiba. A „szegmensenként” után a few-shottal futó változat kategóriánként három
  százalékot adott egy helyett: ezt nem fogalmaztuk tovább, mert a kérdés egy arányt kér.
- A dinamikus few-shot összesítve alig javít (49/50 vs. 48/50, ~7%-kal több tokenért), de a
  házi szokásban igen: az „utolsó negyedév” a lezárt III. negyedév, és ezt few-shottal két
  futásból kétszer, nélküle egyszer sem találta el. Erős modellnél a séma kommentjei és a
  szabályok adják a legtöbbet; a példa ott segít, ahol a helyes válasz nem következik a sémából.

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
- [x] Élő próba Claude-dal és Voyage-dzsal: recall@5 a valódi embeddinggel, idézett válaszok

**Kész, ha:** „Mennyi a késedelmi kamat?” jellegű kérdésekre helyes, idézett válasz jön,
és a jogosultság nélküli dokumentum nem jelenik meg.

**Állapot:** a teljes út kész és tesztelt: betöltés, hibrid keresés, olvasási szint, idézett
válasz, napló. A kulcs nélküli (hash-alapú) embeddinggel a keresési eval **recall@5 = 17/17**,
MRR 0,75, és a három szivárgáspróbán egyetlen belső dokumentum sem jutott fiókvezetőhöz. A
válasz útja ál-LLM-mel tesztelt (idézet-ellenőrzés, napló, tokenkeret). A `voyage-4`-gyel
recall@5 = 17/17, **MRR 0,94**, szivárgás 0. Claude-dal a „Mennyi a késedelmi kamat a személyi
kölcsönnél?” kérdésre idézett, helyes válasz jön (ügyleti kamat + 3 százalékpont, 17,90%); a
fiókvezető a belső árazási szabályzatot nem kapja meg, és a modell azt mondja, a források nem
tartalmazzák a választ.

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

- [x] `Conversation`, `Message` modellek (a `messages` csak hozzáfűzhető, a `query_log` kap `conversation_id`-t)
- [x] `agent/tools.py`: `query_database`, `search_documents`, `describe_schema`, `get_metric_definition` (`data/metrics.yaml`), mindegyik Pydantic-sémával; az eszközkészlet szerepkörfüggő
- [x] Tool-use ciklus: max. 6 hívás, tokenkeret minden modellhívás előtt, határidő az egész üzenetre, hibakezelés eszközönként (ADR-009)
- [x] Beszélgetés-memória: kérdések és végső válaszok; 8 forduló fölött összefoglaló (Haiku), a legutóbbi fele szó szerint
- [x] SSE-stream: `turn_start`, `text`, `tool_start`, `tool_result`, `done`, `error`; egy beszélgetésben egyszerre egy válasz (advisory lock, 409)
- [x] Indirekt prompt injection teszt: mérgezett dokumentum; egy azt követő modell sem kap több jogot (szkriptelt teszt), és a valódi modell nem követi (élő teszt)
- [x] Vegyes eval-kérdések (SQL + dokumentum): `finql eval agent`, 10 kérdés (eszközök, idézett dokumentum, szám a válaszban, szivárgás, prompt-kinyerés)
- [x] Élő próba és eval Claude-dal: a „kész, ha” kérdés streamelve, és a 10 kérdés eredménye

**Kész, ha:** „Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?”
egy válaszban, számmal és idézettel érkezik, streamelve.

**Állapot:** a teljes út kész és tesztelt: a beszélgetés, a stream, az eszközök a felhasználó
jogaival, a korlátok, a memória és az összefoglaló, a napló. A „kész, ha” kérdés API-kulcs
nélkül is végigfut: a demóterv a pécsi fiókvezetőnek a saját fiókja számát adja, és a
követeléskezelési szabályzatot idézi, streamelve. A valódi modellel (2026-10-27) az élő teszt
zöld (szám és idézet, streamelve; a mérgezett dokumentumot nem követi), és az agent evalja
**10/10**, 0 biztonsági hiba, 2,0 eszközhívás és ~12 600 token kérdésenként, p50 8,0 s.

**Tanulságok:**
- A tool runner helyett saját ciklus: minden lépést tárolni, költségkeretre ellenőrizni és
  streamelni kell, és a ciklusnak szkriptelt modellel is futnia kell a tesztekben. A
  szolgáltatói réteg így egyetlen streamelt fordulóra szűkül.
- A memória a kérdés és a végső válasz, nem a teljes átirat. A korábbi eszközeredmények
  elavulnak, és sok tokenbe kerülnek; a gondolkodási blokkok csak a fordulón belül kellenek.
  Egy visszakérdezés újra hívja az eszközöket.
- A streamelt szöveg hivatkozásai már elmentek, mire a kód ellenőrizni tudja őket. Ezért a
  `done` esemény hozza a végleges, ellenőrzött választ, és a kliens azt mutatja.
- Az időkorlát nem foghat át `yield`-et: az, hogy a kliens mennyi idő alatt olvas, nem a modell
  ideje. A határidőt minden várakozásra külön alkalmazzuk.
- Amit a stream előtt el lehet dönteni (jogosultság, keret, foglalt beszélgetés), azt
  függőségben döntjük el: a stream megkezdése után a státuszkód már 200.

---

## 7. fázis – UI, telepítés, demó

**Cél:** egy kattintható demó, amely egy paranccsal elindul, és egy PaaS-on is futhat.

- [x] Webes felület (`web/static/`, ADR-010): bejelentkezés, beszélgetések, a válasz streamelve; eszközhívásonként a kérdés, a futtatott SQL, az eredménytábla, a talált források; a végén az ellenőrzött válasz `[n]` hivatkozásokkal. Statikus oldal build lépés nélkül, csak szövegcsomópontokból, szigorú CSP-vel. (HTMX helyett: az SSE egy `POST`-ra jön, azt az `EventSource` nem tudja.)
- [x] `Dockerfile` (kétlépcsős, uv, nem root), `docker compose up` egy paranccsal: `db` → `setup` (szerepkörök, migrációk, adatok, demófelhasználók, dokumentumok; idempotens) → `app`
- [x] PaaS-konfiguráció: `railway.json` (pre-deploy `setup`, `/ready`), lépésenkénti leírás (`docs/08-telepites.md`), Fly.io és Render változattal
- [ ] Telepítés a Railway-re (fiók kell hozzá; a lépések a 08-as dokumentumban)
- [x] Demó GIF és képernyőkép (`scripts/capture_demo.py`, Playwright), architektúraábra és eval-eredmények a README-ben
- [x] „Tanulságok” szakasz a README-ben

**Kész, ha:** `cp .env.example .env && docker compose up` után a böngészőben egy fiókvezető
megkérdezi a „kész, ha” kérdést, és streamelve látja az SQL-t, az eredményt és az idézett
szabályzatot.

**Állapot:** üres adatbázisról a `docker compose up` ~1,5 perc alatt indul (ebből ~1 perc a
2 millió tranzakció). A második indításkor a `setup` semmit nem tölt be újra. A felület a
konténerből kulcs nélkül végigviszi a „kész, ha” kérdést; a README GIF-je így készült. A
nyilvános telepítéshez Railway-fiók kell; a konfiguráció és a lépések készen vannak.

**Tanulságok:**
- Az `EventSource` csak `GET`-et küld, és fejlécet sem tud: egy `POST`-ra jövő, JWT-vel
  védett streamhez `fetch` és egy 30 soros SSE-olvasó kell. Ez dönti el a felület
  technológiáját is: ha úgyis kell szkript, a szerveroldali sablon csak második réteg.
- A felület a legkönnyebb XSS-cél: modellkimenetet és dokumentumszöveget mutat. Ezt nem a
  szűrés oldja meg, hanem hogy semmi nem megy át HTML-értelmezőn. A CSP csak második vonal.
- A konténer előkészítése akkor biztonságos, ha minden lépése idempotens (`seed --if-empty`,
  hash-alapú ingest, `bootstrap`). Így ugyanaz a parancs fut az első és a századik indításkor,
  helyben és PaaS-on.
- Egy helyen legyenek a jelszavak: a Compose a `.env` URL-jeit használja, és csak a hosztot
  cseréli. Egy második jelszókészlet a konténerhez előbb-utóbb eltérne az elsőtől.

---

## 8. fázis – Haladó (válogatható)

- [x] OpenTelemetry-trace (FastAPI → LLM → DB), vagy Langfuse az LLM-hívásokhoz (OpenTelemetry, helyben Jaegerrel; ADR-014)
- [x] Hash-láncolt `query_log` (`prev_hash`, `row_hash`): a naplóból törölt vagy módosított sor kimutatható (az `answer_log` is; ADR-012)
- [x] MCP-szerver: a `query_database` és a `search_documents` eszköz MCP-n keresztül, így Claude Desktopból is használható (`finql mcp`, ADR-013)
- [ ] Szemantikus válasz-cache (hasonló kérdés + ugyanaz a szerepkör → cache-elt SQL)
- [ ] Materializált nézetek frissítése ütemezve, adatfrissességi metaadat a válaszban
- [ ] Django + Django Ninja változat egy moduljáról, összehasonlító jegyzettel

**Állapot – hash-láncolt napló:** a `query_log` és az `answer_log` sorait egy trigger fűzi
láncba (`chain_seq`, `prev_hash`, `row_hash`); a migráció a meglévő sorokat is láncba fűzte.
Ellenőrzés: `GET /audit/chain` (auditor, admin) és `finql audit verify --anchor` (külső
horgonnyal, ütemezhető, hibánál 1-es kilépési kód). 12 integrációs teszt: egyidejű írók, módosítás,
törlés, átkötés, session-beállítások, új oszlop, horgony, végpont, CLI.

**Tanulságok – hash-láncolt napló:**
- A láncot az adatbázis építi, nem az alkalmazás: amit az alkalmazás a lánc oszlopaiba küld,
  felülíródik. Így a lánc a legkisebb jogú író hibáitól is független.
- A sor szöveges alakja session-beállításfüggő (időzóna, float, bytea): ugyanaz a sor más
  hash-t adott volna egy másik időzónájú sessionben. A függvények ezért rögzítik a beállításokat,
  és egy teszt idegen beállításokkal ellenőriz.
- Egy új oszlop az összes régi sor hash-ét megváltoztatta volna (a JSON-alakban új kulcs). A
  `NULL` értékek ezért kimaradnak a hash-ből; ezt a döntés leírása közben vettem észre, nem
  tesztből, ezért utólag teszt is lett rá.
- A lánc önmagában nem véd a teljes újraírás és a végéről törlés ellen: ehhez külső horgony
  kell. A naplót nem az teszi hitelessé, hogy láncolt, hanem hogy a feje máshol is megvan.

**Állapot – MCP-szerver:** a `finql mcp` stdio-n adja az agent négy eszközét egy MCP-kliensnek,
a `FINQL_MCP_EMAIL` felhasználó jogaival. 8 integrációs teszt, köztük egy valódi stdio-alfolyamat.
Élő próba a valódi Claude-dal: egy MCP-kliens stdio-n elindította a szervert, a
`query_database` a teljes láncon ment át, a napló `mcp-` azonosítóval rögzítette, és a hash-lánc ép
maradt.

**Tanulságok – MCP-szerver:**
- Az eszközréteg már az agentnél is a modelltől független volt (Pydantic-bemenet, hibaeredmény,
  jogosultság a felhasználó rekordjából). Ezért az MCP-szerver vékony réteg lett, nem második
  megvalósítás.
- Az idegen modell ugyanúgy nem kap SQL-eszközt, mint a saját agent: a kérdés a teljes láncon
  megy át. Egy `run_sql` eszköz épp a validátor előtti rétegeket (saját prompt, few-shot)
  kerülné meg.
- Az SDK 2.x-es főverzió volt (a `FastMCP` neve `MCPServer` lett). A telepített csomagból
  ellenőriztük az API-t, nem emlékezetből írtuk; egy régi minta importhibával állt volna meg.
- Egy MCP-szervert a kliens indít, tetszőleges munkakönyvtárból: a munkakönyvtárhoz relatív
  fájlútvonal (`data/metrics.yaml`) ott elhasalt volna. A stdio-teszt ezért idegen könyvtárból
  indít.

**Állapot – nyomkövetés:** egy kérés egy nyom, a FastAPI-kéréstől a modellhívásokon és az
eszközökön át minden SQL-utasításig. A Jaeger egy Compose-profil mögött fut. Élő próba a
valódi modellel: a „kész, ha” kérdés nyoma 52 span, 11,6 s, ebből kb. 10 s a három
modellhívás, a lekérdezés 82 ms. 9 teszt: 5 integrációs, 4 egység.

**Tanulságok – nyomkövetés:**
- Két hibát csak a valódi nyom mutatott meg, a zöld egységtesztek nem. (1) Az OpenTelemetry
  SQLAlchemy-csomagja a 2.1-es SQLAlchemyvel csendben semmit nem mér; helyette saját, kb. 40
  soros eseménykezelő mér. (2) A streamelt válasz minden darabja külön `http send` spant kapott,
  több százat egy kérésben.
- Az Anthropic SDK és az MCP SDK maga is spanokat készít. A saját modellhívás-spant ezért
  kivettük. Az SDK egy környezeti változóra a prompt szövegét is rögzítené; ezt kódban tiltjuk,
  és a teszt a tiltás nélkül elbukik.
- Egy aszinkron generátor köré nem lehet `with`-tel spant tenni: a `yield` a span kontextusát a
  hívóban hagyná. A `traced_stream` a kontextust csak a generátor lépéseire kapcsolja be.
- Az MCP-szerver stdio-ját a naplózás is szennyezte: a konfigurálatlan structlog a stdout-ra ír,
  és az indulási sor a protokoll csatornájára ment. Egy teszt most a teljes stdout-ot nézi.
- A nyom megmutatta, hová megy az idő: a válaszidő szinte csak modellidő. Egy gyorsításnak
  ezért a modellhívások számánál és méreténél kell kezdődnie, nem az SQL-nél.
