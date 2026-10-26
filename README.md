# FinQL: természetes nyelvű elemző asszisztens banki adatokra

> Kérdezz magyarul, és a FinQL biztonságos, ellenőrzött SQL-t futtat egy banki mintaadatbázison.
> A belső szabályzatokból is idézve válaszol, és minden lépést naplóz.

**Státusz:** 0. fázis kész (projektváz, CI). Következik: 1. fázis, a banki adatbázis. Lásd: [ütemterv](docs/07-utemterv.md)

---

## Mit csinál?

| Képesség | Példa | Technika |
|---|---|---|
| **Text-to-SQL** | „Melyik 5 fiókban nőtt legjobban a kártyás költés az előző negyedévhez képest?” | LLM → SQL → validálás (sqlglot) → költségbecslés (EXPLAIN) → read-only futtatás |
| **RAG** | „Mekkora a késedelmi kamat a személyi kölcsönnél?” | Postgres + pgvector, hibrid (vektoros + full-text) keresés, forrásmegjelöléssel |
| **Agent** | „Hány ügyfelünk késik 90 napnál többet, és mit ír erről a behajtási szabályzat?” | Eszközhívás: az LLM a saját SQL- és dokumentumkereső eszközeinket hívja |
| **Jogosultság** | A fiókvezető csak a saját fiókja adatait látja | PostgreSQL Row-Level Security + szerepkörök |
| **Audit** | Minden kérdés, generált SQL, elutasítás és tokenköltség naplózva | Csak hozzáfűzhető (append-only) `query_log` |
| **Értékelés** | 50 „arany” kérdés, végrehajtási pontosság mérése | Saját eval harness, riport |

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
uv run poe db-up                  # Postgres 18 + pgvector (Docker)
uv run poe dev                    # http://127.0.0.1:8000/docs
```

Ellenőrzés: `curl 127.0.0.1:8000/ready` → `{"status":"ready","database":"ok"}`

| Parancs | Mit csinál |
|---|---|
| `uv run poe check` | Lint, formázás, típusellenőrzés, tesztek (ugyanaz, mint a CI) |
| `uv run poe test-unit` | Tesztek Docker nélkül |
| `uv run poe db-down` | Postgres leállítása (az adat megmarad) |
| `uv run pre-commit install` | Git-hookok bekapcsolása |

A későbbi fázisokban jönnek: `alembic upgrade head`, `finql seed`, `finql ingest`, `finql eval`.

## Licenc

MIT
