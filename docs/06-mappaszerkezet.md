# 06 – Mappaszerkezet

## Elv: domain szerinti modulok (nem rétegek szerinti mappák)

Kis FastAPI-projektben megszokott a `routers/`, `models/` és `schemas/` mappa. Közepes
méret felett ez szétszórja az egy funkcióhoz tartozó kódot. Itt **domainmodulokat**
használunk: minden modulban megvan a saját `router`, `service`, `models` és `schemas`,
a közös infrastruktúra pedig a `core/` mappában él. Ez egy moduláris monolit, amelyből
szükség esetén egy modul (pl. `rag`) külön szolgáltatássá emelhető.

**Függőségi szabály:** `api → service → (repository / db / llm)`. Modulok egymás
`service` rétegét hívhatják, de egymás `router` rétegét nem. A `core` senkitől sem függ.

## Fa

```text
finql/
├── README.md
├── LICENSE
├── pyproject.toml                 # függőségek, ruff/mypy/pytest/poe beállítások
├── uv.lock
├── .env.example                   # minden env-változó, dummy értékekkel
├── .gitignore
├── .gitattributes                 # LF sorvégek minden platformon
├── .python-version                # 3.12 (uv ebből telepít)
├── .pre-commit-config.yaml
├── Dockerfile                     # többlépcsős build, nem-root user
├── docker-compose.yml             # db (pgvector/pgvector:pg18), api, (ui)
├── alembic.ini
│
├── .github/
│   └── workflows/
│       ├── ci.yml                 # lint → formázás → mypy → pytest (testcontainers)
│       └── eval.yml               # kézi vagy éjszakai eval valódi LLM-mel (secret)
│
├── docs/                          # ez a dokumentáció
│   ├── 01-projekt-terv.md … 07-utemterv.md
│   └── img/                       # diagramok, képernyőképek, demó GIF
│
├── db/                            # DB-FIRST rész: kézzel írt, review-zott SQL
│   ├── roles/                     # 001_roles.sql: szerepkörök, DB-tulajdon (`finql db bootstrap` futtatja)
│   ├── bank/                      # 000_schema … 010_transactions.sql, 020_indexes.sql, 090_grants.sql
│   ├── analytics/                 # nézetek, materializált nézetek, 090_comments.sql
│   └── security/                  # app_ctx függvények, RLS policy-k
│
├── migrations/                    # Alembic
│   ├── env.py                     # SET ROLE finql_owner; include_name: a DB-first sémák kimaradnak az autogenerate-ből
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_bank_schema.py            # run_sql_file("bank/…"): DB-first SQL-fájlok futtatása
│       ├── 0002_analytics_views.py
│       ├── 0003_rls.py
│       └── 0004_app_users.py              # code-first: autogenerate + review
│
├── src/finql/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory, lifespan (pool-ok, katalógus-cache)
│   ├── health.py                  # /health (liveness), /ready (DB-ping, 503 ha nem elérhető)
│   ├── cli.py                     # typer: db bootstrap, seed, ingest, eval, create-user
│   │
│   ├── core/                      # közös infrastruktúra, nincs benne üzleti logika
│   │   ├── config.py              # pydantic-settings
│   │   ├── db.py                  # két engine: app_engine (finql_app), llm_engine (finql_llm_reader)
│   │   ├── bootstrap.py           # szerepkörök + jelszavak a kapcsolati URL-ekből (adminnal)
│   │   ├── sql_files.py           # a db/ SQL-fájljainak futtatása Alembicből
│   │   ├── logging.py             # structlog, request_id
│   │   ├── security.py            # JWT, jelszó-hash (Argon2)
│   │   ├── errors.py              # domain kivételek → HTTP-válaszok
│   │   └── base_model.py          # SQLAlchemy DeclarativeBase (schema="app")
│   │
│   ├── auth/                      # felhasználók, szerepkörök, bejelentkezés
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── models.py              # User
│   │   ├── schemas.py             # TokenResponse, UserOut
│   │   └── dependencies.py        # get_current_user, require_role(...)
│   │
│   ├── llm/                       # provider-független LLM-réteg
│   │   ├── client.py              # LLMClient protokoll
│   │   ├── anthropic_client.py    # Claude-implementáció
│   │   ├── fake_client.py         # determinisztikus mock a tesztekhez
│   │   ├── embeddings.py          # Embedder protokoll + Voyage / helyi implementáció
│   │   ├── usage.py               # token- és költségnaplózás, felhasználói keret
│   │   └── prompts/               # verziózott promptok (.md / .j2)
│   │       ├── text_to_sql.v1.md
│   │       ├── answer_summary.v1.md
│   │       └── rag_answer.v1.md
│   │
│   ├── text_to_sql/
│   │   ├── router.py              # POST /query, GET /query/history, GET /schema
│   │   ├── service.py             # a teljes folyamat összefűzése, önjavító ciklus
│   │   ├── schema_context.py      # analytics-katalógus betöltése és cache-e
│   │   ├── examples.py            # few-shot példák vektoros kiválasztása
│   │   ├── models.py              # SqlExample
│   │   ├── generator.py           # LLM → GeneratedQuery (Pydantic)
│   │   ├── validator.py           # sqlglot AST-szabályok
│   │   ├── cost_guard.py          # EXPLAIN-alapú küszöb
│   │   ├── executor.py            # read-only tranzakció, set_config, sorlimit
│   │   └── schemas.py
│   │
│   ├── rag/
│   │   ├── router.py              # POST /documents/search
│   │   ├── service.py
│   │   ├── models.py              # Document, DocumentChunk
│   │   ├── chunking.py
│   │   ├── retriever.py           # hibrid keresés (RRF)
│   │   └── schemas.py
│   │
│   ├── agent/
│   │   ├── router.py              # beszélgetések, SSE stream
│   │   ├── service.py             # tool-use ciklus, korlátok
│   │   ├── tools.py               # query_database, search_documents, describe_schema, …
│   │   ├── models.py              # Conversation, Message
│   │   └── schemas.py
│   │
│   ├── audit/
│   │   ├── router.py              # GET /audit/queries (auditor)
│   │   ├── service.py             # log_query(...)
│   │   └── models.py              # QueryLog
│   │
│   └── pipelines/                 # adat-pipeline-ok, a CLI-ből indítva
│       ├── seed/
│       │   ├── generator.py       # Faker hu_HU, eloszlások, „történetek”
│       │   ├── reference.py       # fiókok, termékek, kereskedőkategóriák, ünnepnapok
│       │   ├── identifiers.py     # IBAN, adóazonosító jel, adószám (érvényes ellenőrzőszámmal)
│       │   ├── loader.py          # COPY, partíciók, indexek a betöltés után, VACUUM ANALYZE
│       │   └── scales.py          # tiny / small / large
│       └── ingest/
│           ├── loaders.py         # markdown, pdf
│           └── run.py             # hash-alapú inkrementális betöltés
│
├── data/
│   └── documents/                 # szintetikus banki szabályzatok (md), a RAG forrása
│       ├── hitelezesi-szabalyzat.md
│       ├── dijjegyzek-2026.md
│       └── kartyahasznalati-feltetelek.md
│
├── eval/
│   ├── datasets/
│   │   ├── golden.yaml            # kérdés, elvárt SQL, címkék, szerepkör-kontextus
│   │   └── adversarial.yaml       # elutasítandó kérdések
│   ├── runner.py                  # futtatás, eredményhalmazok összevetése
│   ├── metrics.py                 # végrehajtási pontosság, érvényességi arány, késleltetés, tokenek
│   └── reports/                   # generált markdown-riportok (gitignore, kivéve a kiemelteket)
│
└── tests/
    ├── conftest.py                # testcontainers Postgres, migráció, tiny seed, fake LLM
    ├── unit/
    │   ├── text_to_sql/test_validator.py
    │   ├── rag/test_chunking.py
    │   └── …
    └── integration/
        ├── test_rls.py            # fiókvezető csak a sajátját látja, kontextus nélkül 0 sor
        ├── test_readonly.py       # írás az llm_reader szerepkörrel → hiba
        ├── test_query_api.py
        └── test_hybrid_search.py
```

## Konvenciók

| Téma | Szabály |
|---|---|
| Nevek | Kód, táblák és oszlopok angolul (`snake_case`). Dokumentáció, promptok és UI-szövegek magyarul. |
| Migráció | Egy migráció egy logikai változás. A DB-first SQL-fájl és az őt futtató Alembic-verzió egy commitban. |
| Promptok | Fájlban, verziószámmal (`.v1`, `.v2`). A `query_log` és az `eval_runs` rögzíti, melyik verzió futott. |
| Titkok | Csak env-ből. `.env` soha nem kerül a gitbe, a `.env.example` igen. |
| Commitok | [Conventional Commits](https://www.conventionalcommits.org/): `feat(text_to_sql): …`, `docs: …` |
| Ágak | `main` mindig zöld. Fázisonként feature-ág és PR. |
