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

- `LLMClient` protokoll (`generate_structured` a 3. fázistól), és az agenthez `ChatModel` (`stream_turn`: egy streamelt modellforduló eszközökkel, 6. fázis, ADR-009). Az implementáció cserélhető (Anthropic, helyi Ollama, mock a tesztekhez).
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

**Megvalósítás (4. fázis, embedding):**
- `Embedder` protokoll (`llm/embeddings.py`), Voyage-implementáció `voyage-4` modellel,
  1024 dimenzióval. A Voyage REST API-ját közvetlenül hívjuk (`httpx2`, ami az Anthropic SDK-val
  már telepítve van), nem a Voyage SDK-jával: egyetlen végpontot használunk, és így nem jön be
  újabb függőségi fa.
- Kulcs nélküli változat: `HashingEmbedder` (szavak és betűhármasok hash-elése, determinisztikus).
  Csak lexikális hasonlóságot fog meg, ezért nem a Voyage helyettesítője, de a tesztek és a
  kulcs nélküli demó is értelmesen működik vele. A helyi `bge-m3` az 5. fázisban jöhet, ha kell.
- A vektor mellett a modell neve is tárolva van, és a kiválasztás csak az aktuális modell
  vektorait hasonlítja össze; modellváltáskor a `finql examples sync` újra embeddingel.

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

### ADR-007: Eval végrehajtási pontossággal; a few-shot példák a felhasználói üzenetben

**Mit mérünk:** egy arany kérdés akkor helyes, ha a generált SQL **ugyanazt az eredményt** adja,
mint a kézzel írt, nem ha ugyanúgy néz ki (execution accuracy). Az oszlopneveket nem nézzük
(a modell szabadon nevez el), az elvárt oszlopokat érték szerint keressük meg a generáltak között,
a többletoszlop megengedett. Sorrend csak rangsoros kérdésnél számít, a számok 0,05-ös
tűréssel egyeznek (egy tizedesre kerekített százalék is jó), az éjféli időbélyeg egyenlő a
dátumával. A rosszindulatú kérdés akkor helyes, ha nem jön vissza adat: a modell nem ír SQL-t,
a validátor elutasítja, vagy az eredmény üres (csak NULL vagy 0, pl. egy másik fiókra az RLS miatt).

**Ugyanaz a folyamat:** az eval a `text_to_sql.service.run_attempts`-on át kérdez, amin az API is:
validátor, költségőr, önjavítás, minden. Csak a naplózás más: a kísérletek a memóriában
gyűlnek, az eredmény az `eval_runs`/`eval_results` táblákba megy, a `query_log`-ba nem (az nem
felhasználói tevékenység), és a napi tokenkeretet sem terheli.

**Few-shot a felhasználói üzenetben:** a hasonló példák kérdésenként változnak. Ha a
rendszerpromptba kerülnének, minden kérdés megtörné a prompt-cache-t; így a rendszerprompt
(szabályok + séma) bájtra ugyanaz marad. A példák forrása egy YAML-fájl a repóban
(`data/sql_examples.yaml`), amelyet kódként review-zunk; a `finql examples sync` tölti be. Egy
teszt őrzi, hogy egyik példa se egyezzen egy eval-kérdéssel, különben a few-shot hatása helyett
a válasz kiszivárgását mérnénk.

**Orákulum:** egy ál-LLM, amely az elvárt SQL-t adja vissza. Vele a harness (kérdéssorok,
hatókörök, összevetés, tárolás, riport) API-kulcs és költség nélkül tesztelhető: 100%-ot kell adnia.

### ADR-008: Dokumentumok – olvasási szint az SQL-ben, hibrid keresés, csak idézett válasz

**Olvasási szint, nem szerepkör-rang:** a terv eredetileg `min_role`-t írt a dokumentumra, a
szerepkörök azonban nem egy létra. Az auditor nem lát banki adatot, mégis minden szabályzatot
olvas; az elemző a belső szabályzatokat is látja, a fiókvezető nem. A dokumentum ezért
olvasási szintet kap (`general`, `internal`; a Postgres-enum sorrendje adja a `<=`-t), a
szerepkörhöz pedig egy kódban rögzített leképezés rendel szintet (`rag.models.ROLE_ACCESS`).
A szűrés mindkét keresési ág `WHERE`-jében van: a szint fölötti részlet ki sem jön az
adatbázisból, így az LLM-hez és a válaszba sem kerülhet.

**Hibrid keresés, a fúzió Pythonban:** a vektoros ág a jelentést találja meg („mennyibe kerül” ~
„díja”), a magyar szótáras `tsvector` a pontos kifejezéseket (összegek, terméknevek). A két
jelöltlistát (40–40 találat) Reciprocal Rank Fusion egyesíti (k = 60): csak a helyezés számít,
így a koszinusztávolság és a `ts_rank` közös skála nélkül összevethető. A fúzió Pythonban fut,
nem egy nagy SQL-ben: egységtesztelhető, és ha az embedding nem érhető el, a keresés
ugyanazzal a kóddal csak a szöveges ágon megy tovább (`mode: "text"`), nem áll le. A szöveges ág
`OR`-ral köti a szavakat: a `plainto_tsquery` `AND`-je egy nyolcszavas kérdésre csak a mind a
nyolc szót tartalmazó részletet találná meg. A rangsort a `ts_rank_cd` adja, a címsorban talált
szó többet ér.

**Darabolás címsorok mentén:** egy részlet sosem lépi át a címsort, mert a hivatkozás egy
szakaszra mutat, és két témát keverő részlet mindkettőre rosszul illeszkedik. A túl hosszú
szakasz bekezdés, sor, mondat és végső esetben szó szerint vágódik, a táblázat fejléce minden
darabban megmarad, és kis átfedés van (az előző darab utolsó mondatai). Az embeddingbe a
dokumentum címe és a szakasz is bekerül, így a személyi kölcsön „Késedelem” szakasza a
személyi kölcsönről szól.

**Csak idézett válasz:** a források `<source id="n">` címkékben kerülnek a felhasználói
üzenetbe (a rendszerprompt így cache-elhető), és a forrás saját szövegében lévő záró címkét a
kód széttöri. A modell a válasz minden állítása mögé forrásszámot tesz. A kód ellenőrzi a
számokat: a nem létezőket elhagyja, és ha egy „megválaszolt” kérdésnél nem marad érvényes
hivatkozás, a választ nem mutatja meg (`uncited`), csak a találatokat. Banki szabályzatnál az
ellenőrizhetetlen válasz rosszabb a semminél.

**Napló:** minden válasz az `answer_log`-ba kerül. A tábla csak hozzáfűzhető, mint a
`query_log`, és a napi tokenkeret mindkettőből számol. A források `fájl@verzió#részlet` alakban
szerepelnek (pl. `hirdetmeny-kamatok.md@2#3`), nem részletazonosítóval: egy újratöltés új
részleteket ír, a verzió viszont megmondja, melyik szövegre épült a válasz.

### ADR-009: Agent – saját eszközhívási ciklus, válasz-memória, SSE

**Saját ciklus, nem az SDK tool runnere:** az Anthropic SDK tool runnere a ciklust magától
vinné. Itt viszont minden lépésnek több dolga van: üzenetként tárolni kell, tokenkeretet kell
ellenőrizni előtte, eseményként streamelni kell, és határidőn belül kell maradnia. A ciklus
ráadásul a `ChatModel` protokollon fut (`llm/chat.py`), így a tesztek szkriptelt modellel
(`FakeChatModel`), a kulcs nélküli demó egy fix tervvel ugyanazt az utat járja. A szolgáltatói
réteg csak egy modellfordulót streamel (`stream_turn`); a ciklus, a korlátok és a hibakezelés
szolgáltatófüggetlen (`agent/service.py`).

**Korlátok üzenetenként:**
- Legfeljebb 6 eszközhívás. Utána a modell eszközt már nem hívhat (`tool_choice: none`), a
  meglévő eredményekből kell válaszolnia; a korlát fölötti párhuzamos hívások hibaeredményt
  kapnak.
- A napi tokenkeret minden modellhívás előtt ellenőrizve, így a túllépés legfeljebb egy forduló.
- Egy határidő az egész üzenetre (modellhívások és eszközök együtt). Az időkorlát soha nem fog
  át egy `yield`-et: az, hogy a kliens mennyi idő alatt olvassa ki az eseményt, nem a modell ideje.

**Eszközönkénti hibakezelés:** a bemenetet a kód validálja a Pydantic-modell alapján. Az
elutasított SQL, az időtúllépés vagy egy ismeretlen eszköz hibaeredmény a modellnek, nem a
forduló vége. A modell így elmagyarázhatja, vagy másként próbálkozhat. Váratlan hibánál a
modell nem látja a belső részleteket, csak annyit, hogy hiba történt.

**Jogosultság:** minden eszköz a felhasználó jogaival fut: a `query_database` a teljes
text-to-SQL láncon megy át (validátor, költségőr, RLS), a `search_documents` az olvasási
szinttel szűr. Az eszközkészlet szerepkörfüggő: az auditor nem kap adateszközt, mert nem lát
banki adatot. Egy mérgezett dokumentum ezért legfeljebb azt érheti el, hogy a modell olyat
kérdezzen, amit a felhasználó maga is kérdezhetne.

**Memória: kérdés és végső válasz, nem a teljes átirat.** A következő üzenet előzménye a
korábbi kérdések és végső válaszok, a korábbi eszközhívások és gondolkodási blokkok nélkül. A
végső válasz a forduló eredménye, egy visszakérdezés („és fiókonként?”) újra hívhatja az
eszközöket. Az előzmény minden fordulóban ugyanúgy renderelődik, így a prompt-cache működik. A
gondolkodási blokkokat (aláírással) csak a fordulón belül küldjük vissza változatlanul; ott
kötelező, máshol nincs rájuk szükség. 8 korábbi forduló fölött a régebbi fordulókat egy olcsó
modell (Haiku) összefoglalja, és a legutóbbi fele szó szerint marad. Kötegben, nem
fordulónként, hogy a cache-elt előtag a kötegek között változatlan maradjon.

**Prompt-cache:** fix töréspont a rendszerprompt végén (szabályok és eszközök, minden
beszélgetésben azonosak), és automatikus töréspont a növekvő beszélgetés végén. A forduló
közben nem váltunk modellt (nincs refusal-fallback az agentnél): egy másik modell nem
fogadná el az előző gondolkodási blokkjait.

**SSE, a FastAPI natív `EventSourceResponse`-ával:** események: `turn_start`, `text`,
`tool_start`, `tool_result`, `done`, `error`. Ami a stream előtt eldől (nem létező vagy más
beszélgetése, elfogyott keret, már futó válasz), az függőségben dől el, így rendes JSON-hibát
kap. A stream közbeni hibák `error` eseményként jönnek. A streamelt szöveg hivatkozásait a
`done` esemény ellenőrzi: a kliens annak `answer` mezőjét mutatja végső válaszként.

**Egy beszélgetésben egyszerre egy válasz:** két párhuzamos üzenet összefésülné az üzeneteit.
A kérés tranzakciójában vett `pg_try_advisory_xact_lock` véd ellene. A tranzakció a stream
végéig nyitva marad, és a zár vele együtt szabadul fel, bárhogy ér véget a stream; ha foglalt,
409.

**Tárolás:** a `messages` tábla csak hozzáfűzhető, mint a naplók: kérdés, minden
modellforduló, minden eszközhívás bemenettel és eredménnyel, az összefoglalók. A
`query_log.conversation_id` köti az agent SQL-kísérleteit a beszélgetéshez. Az üzenetek
tokenjei a napi keretbe számítanak.

### ADR-010: Webes felület – egy statikus oldal, build lépés nélkül

**Egy HTML-oldal, egy szkript, egy stíluslap, amelyeket a FastAPI szolgál ki** (`web/static/`),
és amelyek ugyanazt az API-t hívják, mint bármely más kliens. A felület vékony réteg: a lényeg
(jogosultság, SQL-ellenőrzés, idézetek ellenőrzése) a szerveren van, a felületnek csak meg
kell mutatnia.

- **Nem HTMX + Jinja:** a válasz SSE-stream egy `POST`-ra. A böngésző `EventSource`-a és az
  arra épülő HTMX-bővítmény csak `GET`-et küld, fejlécet (JWT) nem. A streamet ezért
  `fetch`-csel olvassuk, ahhoz pedig úgyis szkript kell. A szerveroldali sablonok egy második
  megjelenítési réteget adnának az API mellé.
- **Nem Streamlit és nem React:** a Streamlit külön folyamat, és a saját állapotmodellje
  nehezen fér össze egy SSE-streammel. A React build lépést, `node_modules`-t és egy második
  eszközláncot hozna egy négy nézetből álló felülethez.
- **Biztonság:** a felület modellkimenetet, SQL-eredményt és dokumentumszöveget mutat, mind
  megbízhatatlan. Az oldal csak szövegcsomópontokból épül, HTML-ként semmit nem értelmez (egy
  teszt figyeli, hogy ne kerüljön bele `innerHTML`). A szigorú Content-Security-Policy
  (`script-src 'self'`, inline szkript és külső forrás nélkül) a második védvonal. A
  válaszszöveg kis Markdown-részhalmaza (bekezdés, lista, táblázat, félkövér) és a `[n]`
  hivatkozások is DOM-csomópontként készülnek.
- **Token:** `sessionStorage`-ban: a lap bezárásával elvész, és 30 perc után lejár. Egy
  `HttpOnly` süti XSS ellen jobb volna, de CSRF-védelmet kívánna, és az API-nak két
  hitelesítési módot. A szigorú CSP mellett ez a kompromisszum vállalható egy belső eszköznél.
- **A végleges válasz a `done` eseményből:** a streamelt szöveg csak vázlat. A `done` hozza az
  ellenőrzött választ (érvénytelen hivatkozások nélkül) és az idézett forrásokat, a felület a
  vázlatot erre cseréli.

### ADR-011: Konténer és telepítés

- **Kétlépcsős image:** az első lépcső uv-vel, a lock fájl szerint telepít (`uv sync
  --locked`, a függőségek külön rétegben, cache-elve). A második csak a kész környezetet és a
  futáshoz kellő fájlokat kapja (migrációk, `db/`, `data/`), uv és fordító nélkül. Nem rootként
  fut, és a kód a root tulajdonában marad, így a folyamat nem írhatja át a saját kódját.
- **Két parancs, egy image:** `serve` (uvicorn) és `setup` (szerepkörök, migrációk, banki
  adatok, ha még nincsenek, demófelhasználók, dokumentumok, few-shot példák). A `setup` minden
  lépése idempotens, így minden indításkor és minden telepítéskor futhat. Az alkalmazás csak
  akkor indul, ha a `setup` sikeres volt (Compose: `service_completed_successfully`, PaaS:
  pre-deploy parancs).
- **A Compose a `.env`-et használja:** a jelszavak egy helyen maradnak. A konténerben a
  `127.0.0.1` helyett a `db` hoszt kell; ezt az entrypoint cseréli az URL-ekben
  (`FINQL_DB_HOST`), nem egy második jelszókészlet.
- **PaaS: Railway, a Postgres a saját `pgvector/pgvector:pg18` image-ével, kötettel.** A
  menedzselt Postgres-szolgáltatások többsége nem ad superusert. Itt viszont kell: a
  `finql db bootstrap` szerepköröket hoz létre, és a `vector` bővítményt is telepíteni kell. A
  PG18 sem mindenhol elérhető. Ugyanaz az image fut helyben, a CI-ban és a PaaS-on.
- **Kulcs nélkül is indul:** a `.env.example` alapértéke a kulcs nélküli mód (`fake` LLM,
  `hashing` embedding). A `cp .env.example .env && docker compose up` így API-kulcs nélkül
  is teljes, kattintható demót ad; a valódi modellhez két sort kell átírni.

### ADR-012: Hash-láncolt napló, az adatbázisban számolva

- **Mit véd:** az append-only jog az alkalmazást tartja vissza; a nagyobb jogú (tulajdonos,
  DBA) módosítást nem. A `query_log` és az `answer_log` sorai ezért hash-láncot alkotnak: a
  módosított, törölt vagy beszúrt sor a lánc ellenőrzésekor kiderül, a pontos sorszámmal.
- **Az adatbázis számol, triggerben:** így egy hibás, megkerült vagy feltört alkalmazás sem
  írhat rossz láncot, és a lánc a kódváltozásoktól független. Advisory lock állítja sorba az
  írókat (a napló úgyis saját, rövid tranzakcióban íródik), a `chain_seq` egyedi indexe pedig
  biztosítja, hogy a lánc ne ágazhasson el csendben.
- **A hash a sor teljes JSON-alakjára számol, a `NULL` értékek nélkül.** A beállításfüggő
  szöveggé alakítást (időzóna, float, bytea) a függvények rögzítik. Egy új oszlop így magától a
  hash része lesz, nem kell kézi oszloplistát karbantartani. Egy új, `NULL`-os oszlop a régi
  sorok hash-ét nem változtatja meg; egy oszlop törlése, átnevezése vagy típusváltása viszont
  igen, ezért az ilyen migrációnak a láncot is újra kell fűznie (ami maga is egy dokumentált,
  naplózott esemény).
- **Horgony a lánc ellen, amit egészében újraírtak:** a lánc fejét az adatbázison kívül is
  rögzítjük (`finql audit verify --anchor`). Ez olcsó, és nem kell hozzá külső szolgáltatás.
- **Elvetve:** a pgaudit (a műveleteket naplózza, nem a sorok épségét bizonyítja, és superuser
  kell a beállításához); a WORM-tárba vagy külső naplószolgáltatásba másolás (új függőség egy
  portfólióprojektben); HMAC titkos kulccsal (a kulcsot az adatbázisnak vagy az alkalmazásnak
  ismernie kellene, így a nagyobb jogú támadó is ismerné). Ha a fenyegetés ezt kívánja, a
  horgony helyére egy aláírt, külső tár léphet; a lánc változatlan marad.

### ADR-013: MCP-szerver – stdio, az agent eszközrétege, egy felhasználó

- **Ugyanaz az eszközréteg, mint az agenté:** a `Tool`, a `run_tool` és a `tools_for`
  változatlanul szolgál ki egy MCP-klienst. A jogosultság, a bemenet-ellenőrzés, a napló és a
  tokenkeret így nem kétszer van megírva, és nem térhet el. Az alacsony szintű `Server`-t
  használjuk, nem az `MCPServer`-t: az eszközök sémája már Pydantic-modell, a dekorátoros
  regisztráció csak egy második leírást adna ugyanarról.
- **Kérdés, nem SQL:** a kliens modellje (Claude Desktop) nem kap SQL-eszközt. Egy
  `run_sql` eszköz kényelmes lenne, de egy idegen modellt engedne közvetlenül a validátorhoz, a
  saját promptunk és a few-shot nélkül; a `query_database` a teljes text-to-SQL láncon megy át.
- **stdio, egy felhasználó, környezeti változóból:** az MCP-kliens indítja a szervert, és a
  konfigurációjában adja meg a FinQL-felhasználót. A szerver indításkor ugyanúgy bejelentkezik,
  mint a `/auth/token`, és minden kérés előtt újraolvassa a felhasználót.
- **Elvetve (egyelőre): távoli HTTP-szerver.** Az MCP távoli hitelesítése OAuth 2.1-es
  engedélyezési szervert vár; a meglévő 30 perces JWT ehhez nem elég, egy saját OAuth-szerver
  pedig túlnő ezen a projekten. Az eszközréteg ugyanaz maradna, csak a szállítás és a
  hitelesítés cserélődne (`streamable_http_app` a FastAPI alá).
- **Az SDK 2.x-es főverziója:** a `FastMCP` itt már `MCPServer`, a kezelők a konstruktorban
  regisztrálódnak. A kódot a telepített SDK-ból ellenőriztük, nem az 1.x-es mintákból.

### ADR-014: Nyomkövetés – OpenTelemetry, a bank adatai nélkül

- **Egy kérés egy nyom:** a FastAPI-kérés a gyökér, alatta az agent fordulója
  (`invoke_agent`), az eszközök (`execute_tool`), a text-to-SQL lánc (`text_to_sql`,
  `validate_sql`, `execute_sql`), a modell- és embeddinghívások és minden SQL-utasítás. Az MCP-n
  az SDK `tools/call` spanja a gyökér. A GenAI szemantikus konvenciókat követjük, így egy
  általános nézegető (Jaeger „GenAI View”) is érti.
- **Amit a mások megcsinálnak, azt nem duplikáljuk:** az Anthropic SDK és az MCP SDK maga is
  spanokat készít (modell, tokenek, cache, első darabig eltelt idő; MCP-metódus). Ezek a mi
  spanjaink alá kerülnek, saját modellhívás-spant nem írunk.
- **Nincs banki adat a nyomban:** se kérdés, se válasz, se dokumentum, se eredménysor. Az
  Anthropic SDK-nál ezt kódban rögzítjük (`content_mode: metadata_only`), mert egy környezeti
  változó különben bekapcsolhatná; a trace-fejlécet sem küldjük az API-nak. A nyom és a napló
  között a `query_log` azonosítója a híd: a span eseménye, a tartalom a naplóban.
- **Az adatbázis-spanok saját eseménykezelőből:** az OpenTelemetry SQLAlchemy-csomagja csak a
  2.1 előtti SQLAlchemyt támogatja, és 2.1-gyel csendben semmit nem mér. A kurzor-eseményekre
  írt kb. 40 sor verziófüggetlen, és csak az SQL szövegét rögzíti, a paramétereket nem.
- **Stream span-kezelése:** az agent fordulója egy aszinkron generátor. Egy `with` blokk egy
  `yield`-en át a span kontextusát a webszerver kódjában hagyná; a `traced_stream` a kontextust
  csak a generátor saját lépéseire kapcsolja be.
- **Kikapcsolva alapból:** `FINQL_OTEL_ENDPOINT` nélkül nincs exportőr és nincs mérés. Helyben
  a Jaeger egy Compose-profil mögött fut, így az alap `docker compose up` nem változik.

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
| Konténer | Docker Compose (`pgvector/pgvector:pg18`), kétlépcsős alkalmazás-image | ADR-011 |
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
| 007 | Eval végrehajtási pontossággal, az API folyamatán; few-shot a felhasználói üzenetben | Elfogadva |
| 008 | Dokumentumok: olvasási szint az SQL-ben, hibrid keresés RRF-fel, csak idézett válasz | Elfogadva |
| 009 | Agent: saját eszközhívási ciklus korlátokkal, kérdés–válasz memória összefoglalóval, SSE | Elfogadva |
| 010 | Webes felület: statikus oldal és szkript build nélkül, csak szövegcsomópontok, szigorú CSP | Elfogadva |
| 011 | Kétlépcsős, nem root image; idempotens `setup`; Railway a saját pgvector-image-dzsel | Elfogadva |
| 012 | Hash-láncolt `query_log` és `answer_log`: trigger az adatbázisban, külső horgony | Elfogadva |
| 013 | MCP-szerver stdio-n: az agent eszközrétege, kérdés (nem SQL), egy felhasználó jogaival | Elfogadva |
| 014 | OpenTelemetry-nyomkövetés: egy kérés egy nyom, a SDK-k spanjaival, banki adat nélkül | Elfogadva |

Új döntésnél új sor kerül ide, és egy rövid ADR-szakasz a fenti formában.
