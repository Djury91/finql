# FinQL: természetes nyelvű elemző asszisztens banki adatokra

> Kérdezz magyarul, és a FinQL biztonságos, ellenőrzött SQL-t futtat egy banki mintaadatbázison.
> A belső szabályzatokból is idézve válaszol, és minden lépést naplóz.

**Státusz:** 5. fázis: a dokumentumkeresés (RAG) kész: 20 szintetikus szabályzat, hibrid keresés, olvasási szint az SQL-ben, idézett válaszok. A 4. fázis eval harnessével együtt a valódi modellel mért számok API-kulcsra várnak. Lásd: [ütemterv](docs/07-utemterv.md)

---

## Mit csinál?

| Képesség | Példa | Technika |
|---|---|---|
| **Text-to-SQL** | „Melyik 5 fiókban nőtt legjobban a kártyás költés az előző negyedévhez képest?” | LLM → SQL → validálás (sqlglot) → költségbecslés (EXPLAIN) → read-only futtatás |
| **RAG** | „Mekkora a késedelmi kamat a személyi kölcsönnél?” | Postgres + pgvector, hibrid (vektoros + full-text) keresés, forrásmegjelöléssel |
| **Agent** | „Hány ügyfelünk késik 90 napnál többet, és mit ír erről a behajtási szabályzat?” | Eszközhívás: az LLM a saját SQL- és dokumentumkereső eszközeinket hívja |
| **Jogosultság** | A fiókvezető csak a saját fiókja adatait látja | PostgreSQL Row-Level Security + szerepkörök |
| **Audit** | Minden kérdés, generált SQL, elutasítás és tokenköltség naplózva | Csak hozzáfűzhető (append-only) `query_log` |
| **Értékelés** | 50 „arany” és 20 rosszindulatú kérdés, végrehajtási pontosság mérése | Saját eval harness, riport, futások az adatbázisban |

## Miért ez a projekt?

A legtöbb LLM-demó a promptolásnál véget ér. Éles rendszerben a nehéz rész az **adat**:
sémaismeret, jogosultság, lekérdezés-validálás, teljesítmény és naplózás. Ez a projekt
pont ezt mutatja meg: backend, SQL és AI együtt, egy hiteles pénzügyi domainen.

## Technológia röviden

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2
- **Adatbázis:** PostgreSQL 18 + pgvector, RLS, particionálás, nézetek mint szemantikai réteg
- **LLM:** Claude (Anthropic API) provider-független interfész mögött, embedding: Voyage AI / helyi modell
- **Eszközök:** uv, ruff, mypy, pytest + testcontainers, Docker Compose, GitHub Actions

A döntések indoklása: [02 – Technológiai döntések](docs/02-technologiai-dontesek.md).

## Dokumentáció

| # | Dokumentum | Tartalom |
|---|---|---|
| 01 | [Projektterv](docs/01-projekt-terv.md) | Cél, felhasználók, méretezés, scope |
| 02 | [Technológiai döntések](docs/02-technologiai-dontesek.md) | Django vs FastAPI méret szerint, code-first vs DB-first, döntésnapló |
| 03 | [Architektúra](docs/03-architektura.md) | Komponensek, kérésfolyamatok |
| 04 | [Adatbázis](docs/04-adatbazis.md) | Sémák, táblák, szerepkörök, RLS, indexek |
| 05 | [Text-to-SQL biztonság](docs/05-text-to-sql-biztonsag.md) | Fenyegetésmodell, védelmi rétegek |
| 06 | [Mappaszerkezet](docs/06-mappaszerkezet.md) | Repó felépítése, modulok felelőssége |
| 07 | [Ütemterv](docs/07-utemterv.md) | Fázisok lépésről lépésre, kész-kritériumok |

## Gyors indítás

Előfeltétel: [uv](https://docs.astral.sh/uv/) és Docker.

```bash
cp .env.example .env              # írd át a jelszavakat
uv sync                           # Python 3.12 + függőségek
uv run poe db-setup               # Postgres (Docker) → szerepkörök → migrációk → ~2 millió tranzakció (~1 perc)
uv run finql user demo           # demófelhasználók szerepkörönként (jelszó: FINQL_DEMO_PASSWORD)
uv run poe dev                    # http://127.0.0.1:8000/docs
```

A `db-setup` lépései külön is futtathatók: `db-up`, `db-bootstrap` (szerepkörök és jelszavak, adminnal),
`db-migrate` (`alembic upgrade head`), `seed` (`finql seed --scale small`; újratöltés: `--reset`).

Ellenőrzés: `curl 127.0.0.1:8000/ready` → `{"status":"ready","database":"ok"}`

Bejelentkezés: a `/docs` oldalon az **Authorize** gombbal, pl. `pecs@minta-bank.example`
(pécsi fiókvezető) vagy `elemzo@minta-bank.example` (elemző) és a `FINQL_DEMO_PASSWORD`.
Utána a `GET /auth/me` a szerepkört és a fiókot adja vissza.

### Kérdezés (text-to-SQL)

A `POST /query` törzse: `{"question": "Hány 90+ napos késedelmes hitelünk van?"}`. A válasz a
futtatott SQL, a magyarázat, a feltételezések és az eredménytábla. Ugyanaz a kérdés az elemzőnek
az egész bankra, a pécsi fiókvezetőnek csak a pécsi fiókra felel (Row-Level Security).

- **Claude-dal:** `FINQL_ANTHROPIC_API_KEY` a `.env`-ben (alapmodell: `claude-sonnet-5-5`).
- **API-kulcs nélkül:** `FINQL_LLM_PROVIDER=fake` – a [projektterv](docs/01-projekt-terv.md)
  példakérdéseire kézzel írt SQL-lel válaszol, a biztonsági lánc ugyanaz.

Minden kísérlet (az elutasítottak is) a `query_log` táblába kerül: `GET /query/history` (saját),
`GET /audit/queries` (auditor). Az LLM által látott séma: `GET /schema`.

### Minőségmérés (eval) és few-shot

```bash
uv run finql examples sync            # few-shot példák betöltése embeddinggel (FINQL_VOYAGE_API_KEY)
uv run finql eval run                 # 50 arany + 20 rosszindulatú kérdés a valódi modellel
uv run finql eval run --few-shot 3    # ugyanez a 3 leghasonlóbb példával a promptban
uv run finql eval compare 1 2         # két futás: fő számok, javult és romlott kérdések
uv run poe eval-oracle                # a harness önellenőrzése API-kulcs nélkül (100%-ot kell adnia)
```

Egy arany kérdés akkor helyes, ha a generált SQL ugyanazt az eredményt adja, mint a kézzel írt
(az oszlopnév és a sorrend nem számít, csak rangsornál). A rosszindulatú kérdésre nem jöhet vissza
adat. A riport az `eval/reports/` mappába kerül, a futások az `eval_runs`/`eval_results` táblákba.
A módszer: [ADR-007](docs/02-technologiai-dontesek.md).

Kulcs nélkül a few-shot a `FINQL_EMBEDDING_PROVIDER=hashing` beállítással is kipróbálható (csak
lexikális hasonlóság). Az `eval.yml` workflow kézzel indítható a GitHubon (secretek:
`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`).

### Dokumentumok (RAG)

```bash
uv run finql ingest                   # data/documents → darabolás, embedding (csak a változottak)
uv run finql eval retrieval           # 20 kérdés: recall@5, MRR, és nem szivárog-e belső dokumentum
```

- `POST /documents/search` `{"query": "késedelmi kamat", "top_k": 5}`: hibrid keresés (vektoros +
  magyar teljes szöveges, Reciprocal Rank Fusion). A fiókvezető csak az általános dokumentumokat
  látja, az elemző és az auditor a belsőket is; a szűrés az SQL-ben történik.
- `POST /documents/answer` `{"question": "Mennyi a késedelmi kamat a személyi kölcsönnél?"}`:
  válasz a dokumentumokból, minden állítás mögött a forrás számával (`[1]`), a forrásokkal
  együtt. Hivatkozás nélküli választ nem ad. Minden válasz az `answer_log`-ba kerül.

Kulcs nélkül: `FINQL_EMBEDDING_PROVIDER=hashing` (lexikális hasonlóság), és embedding nélkül is
működik a keresés, csak szöveges módban. `FINQL_LLM_PROVIDER=fake` esetén a válasz a legjobb
forrás eleje, idézve. A döntések: [ADR-008](docs/02-technologiai-dontesek.md).

### Fejlesztői parancsok

| Parancs | Mit csinál |
|---|---|
| `uv run poe check` | Lint, formázás, típusellenőrzés, tesztek (ugyanaz, mint a CI) |
| `uv run poe test-unit` | Tesztek Docker nélkül |
| `uv run poe test-llm` | Néhány kérdés a valódi Claude-dal (API-kulcs kell, pár cent) |
| `uv run poe db-down` | Postgres leállítása (az adat megmarad) |
| `uv run pre-commit install` | Git-hookok bekapcsolása |

## Licenc

MIT
