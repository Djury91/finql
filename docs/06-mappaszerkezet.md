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
├── Dockerfile                     # kétlépcsős build (uv), nem root, parancsok: serve, setup
├── .dockerignore                  # titkok, privát jegyzetek, tesztek, cache-ek kimaradnak
├── docker-compose.yml             # db (pgvector/pgvector:pg18) → setup → app
├── railway.json                   # PaaS: build a Dockerfile-ból, pre-deploy setup, /ready
├── alembic.ini
│
├── docker/
│   └── entrypoint.sh              # serve | setup | bármi más; a Compose-ban a DB-hoszt cseréje
│
├── scripts/
│   └── capture_demo.py            # a README demó-GIF-je és képernyőképe (Playwright, nem függőség)
│
├── .github/
│   └── workflows/
│       ├── ci.yml                 # lint → formázás → mypy → pytest (testcontainers)
│       └── eval.yml               # kézi vagy éjszakai eval valódi LLM-mel (secret)
│
├── docs/                          # ez a dokumentáció
│   ├── 01-projekt-terv.md … 08-telepites.md
│   └── img/                       # demo.gif, chat.png (scripts/capture_demo.py)
│
├── db/                            # DB-FIRST rész: kézzel írt, review-zott SQL
│   ├── roles/                     # 001_roles.sql: szerepkörök, DB-tulajdon (`finql db bootstrap` futtatja)
│   ├── bank/                      # 000_schema … 010_transactions.sql, 020_indexes.sql, 090_grants.sql
│   ├── analytics/                 # nézetek, havi összesítő, 090_comments.sql, 099_ownership_grants.sql
│   ├── security/                  # 001_app_ctx.sql (session-kontextus), 010_rls.sql (policy-k)
│   ├── extensions/                # 001_pgvector.sql: a vector bővítmény (`finql db bootstrap`, superuser)
│   └── app/                       # 000_schema.sql: az app séma és a finql_app alapjogai
│
├── migrations/                    # Alembic
│   ├── env.py                     # SET ROLE finql_owner; include_name: a DB-first sémák kimaradnak az autogenerate-ből
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_bank_schema.py            # run_sql_file("bank/…"): DB-first SQL-fájlok futtatása
│       ├── 0002_rls.py                    # app_ctx + policy-k (a nézetek már ezekre épülnek)
│       ├── 0003_analytics_views.py
│       ├── 0004_app_schema_and_users.py   # code-first: autogenerate + review
│       ├── 0005_query_log.py
│       ├── 0006_sql_examples.py
│       ├── 0007_eval_runs.py
│       ├── 0008_documents_and_answer_log.py
│       └── 0009_conversations_and_messages.py
│
├── src/finql/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory, lifespan (pool-ok, katalógus-cache)
│   ├── health.py                  # /health (liveness), /ready (DB-ping, 503 ha nem elérhető)
│   ├── cli.py                     # typer: db bootstrap, seed, user create/demo, examples sync, eval run/compare, ingest
│   ├── models.py                  # minden ORM-modul egy helyen (Alembic target_metadata)
│   │
│   ├── core/                      # közös infrastruktúra, nincs benne üzleti logika
│   │   ├── config.py              # pydantic-settings
│   │   ├── db.py                  # két engine: app_engine (finql_app), llm_engine (finql_llm_reader)
│   │   ├── bootstrap.py           # szerepkörök + jelszavak a kapcsolati URL-ekből (adminnal)
│   │   ├── sql_files.py           # a db/ SQL-fájljainak futtatása Alembicből
│   │   ├── logging.py             # structlog, request_id
│   │   ├── security.py            # JWT, jelszó-hash (Argon2id)
│   │   ├── deps.py                # közös függőségek: DbSession, AppSettings
│   │   ├── errors.py              # domain kivételek → HTTP-válaszok
│   │   └── base_model.py          # SQLAlchemy DeclarativeBase (schema="app")
│   │
│   ├── auth/                      # felhasználók, szerepkörök, bejelentkezés
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── models.py              # User
│   │   ├── schemas.py             # TokenResponse, UserOut
│   │   ├── dependencies.py        # get_current_user, require_role(...)
│   │   └── admin.py               # felhasználókezelés a CLI-ből (fiókkód → branch_id)
│   │
│   ├── llm/                       # provider-független LLM-réteg
│   │   ├── client.py              # LLMClient protokoll (egylépéses, strukturált válasz)
│   │   ├── chat.py                # ChatModel protokoll: egy streamelt modellforduló eszközökkel
│   │   ├── anthropic_client.py    # Claude-implementáció (mindkét protokoll)
│   │   ├── fake_client.py         # determinisztikus mock a tesztekhez
│   │   ├── fake_chat.py           # szkriptelt agent-modell a tesztekhez
│   │   ├── embeddings.py          # Embedder protokoll + Voyage, hash-alapú (kulcs nélkül)
│   │   ├── usage.py               # token- és költségnaplózás, felhasználói keret
│   │   └── prompts/               # verziózott promptok (.md / .j2)
│   │       ├── text_to_sql.v1.md
│   │       ├── rag_answer.v1.md
│   │       ├── agent.v1.md
│   │       └── conversation_summary.v1.md
│   │
│   ├── text_to_sql/
│   │   ├── router.py              # POST /query, GET /query/history, GET /schema
│   │   ├── service.py             # a teljes folyamat összefűzése, önjavító ciklus
│   │   ├── schema_context.py      # analytics-katalógus betöltése és cache-e
│   │   ├── examples.py            # few-shot példák: YAML → app.sql_examples (sync), vektoros kiválasztás
│   │   ├── models.py              # SqlExample
│   │   ├── generator.py           # LLM → GeneratedQuery (Pydantic)
│   │   ├── validator.py           # sqlglot AST-szabályok
│   │   ├── cost_guard.py          # EXPLAIN-alapú küszöb
│   │   ├── executor.py            # read-only tranzakció, set_config, sorlimit
│   │   ├── demo.py                # példakérdések kézi SQL-lel: ál-LLM API-kulcs nélkül
│   │   └── schemas.py
│   │
│   ├── rag/
│   │   ├── router.py              # POST /documents/search, POST /documents/answer
│   │   ├── sources.py             # a forrásfájlok: YAML-fejléc, tartalom-hash
│   │   ├── chunking.py            # címsor-alapú darabolás, átfedéssel
│   │   ├── ingest.py              # `finql ingest`: hash-alapú inkrementális betöltés
│   │   ├── retriever.py           # hibrid keresés (vektor + full-text, RRF), olvasási szint SQL-ben
│   │   ├── answer.py              # idézett válasz: források a promptban, hivatkozás-ellenőrzés, napló
│   │   ├── demo.py                # kulcs nélküli mód: a legjobb forrás eleje, idézve
│   │   ├── models.py              # Document, DocumentChunk, AnswerLog; szerepkör → olvasási szint
│   │   └── schemas.py
│   │
│   ├── agent/
│   │   ├── router.py              # beszélgetések, SSE stream, egy válasz egyszerre (zár)
│   │   ├── service.py             # tool-use ciklus: korlátok, események, hivatkozás-ellenőrzés
│   │   ├── tools.py               # query_database, search_documents, describe_schema, get_metric_definition
│   │   ├── memory.py              # üzenetek tárolása, előzmény, összefoglaló (Haiku)
│   │   ├── metrics.py             # üzleti mutatók katalógusa (data/metrics.yaml)
│   │   ├── demo.py                # kulcs nélküli mód: fix terv, az eszközök eredményét idézi
│   │   ├── models.py              # Conversation, Message
│   │   └── schemas.py
│   │
│   ├── eval/                      # a minőség mérése (`finql eval run`)
│   │   ├── datasets.py            # a kérdéssorok sémája és betöltése
│   │   ├── compare.py             # végrehajtási pontosság: eredményhalmazok összevetése
│   │   ├── runner.py              # kérdések az API folyamatán (service.run_attempts), bírálat
│   │   ├── metrics.py             # pontosság, érvényes SQL, elutasítás, p50/p95, tokenek
│   │   ├── report.py              # markdown-riport és két futás összevetése
│   │   ├── store.py               # eval_runs / eval_results
│   │   ├── oracle.py              # ál-LLM az elvárt SQL-lel: a harness önellenőrzése
│   │   ├── retrieval.py           # dokumentumkeresés: recall@5, MRR, szivárgás (`finql eval retrieval`)
│   │   ├── agent.py               # agent: eszközök, idézet, szám a válaszban (`finql eval agent`)
│   │   ├── models.py              # EvalRun, EvalResult
│   │   └── run.py                 # a CLI-parancsok összekötése (beállítások → futás → riport)
│   │
│   ├── audit/
│   │   ├── router.py              # GET /audit/queries, /audit/conversations (auditor)
│   │   ├── service.py             # log_query(...): saját tranzakcióban
│   │   ├── models.py              # QueryLog
│   │   └── schemas.py
│   │
│   ├── web/                       # webes felület (ADR-010)
│   │   ├── router.py              # GET / (CSP-fejlécekkel), GET /web/config
│   │   └── static/                # index.html, app.js (SSE-olvasó, csak szövegcsomópontok), app.css
│   │
│   └── pipelines/                 # adat-pipeline-ok, a CLI-ből indítva
│       └── seed/
│           ├── generator.py       # Faker hu_HU, eloszlások, „történetek”
│           ├── reference.py       # fiókok, termékek, kereskedőkategóriák, ünnepnapok
│           ├── identifiers.py     # IBAN, adóazonosító jel, adószám (érvényes ellenőrzőszámmal)
│           ├── loader.py          # COPY, partíciók, indexek a betöltés után, VACUUM ANALYZE
│           └── scales.py          # tiny / small / large
│
├── data/
│   ├── sql_examples.yaml          # few-shot példák (kérdés + SQL), `finql examples sync`
│   ├── metrics.yaml               # üzleti mutatók: definíció, számítás (get_metric_definition)
│   └── documents/                 # 20 szintetikus banki dokumentum (md + YAML-fejléc), `finql ingest`
│       ├── README.md              # a fejléc formátuma (nem töltődik be)
│       ├── hirdetmeny-kamatok.md
│       ├── kovetelkezelesi-szabalyzat.md
│       └── …
│
├── eval/                          # adat: a kód a src/finql/eval csomagban (a CLI-ből importálható)
│   ├── datasets/
│   │   ├── golden.yaml            # 50 kérdés: elvárt SQL, nehézség, címkék, szerepkör
│   │   ├── adversarial.yaml       # 20 elutasítandó kérdés, kategóriánként
│   │   ├── retrieval.yaml         # 20 dokumentumkeresési kérdés: elvárt dokumentum, szerepkör
│   │   └── agent.yaml             # 10 agent-kérdés: eszközök, idézendő dokumentum, elvárt szám
│   └── reports/                   # generált markdown-riportok (gitignore, kivéve a kiemelteket)
│
└── tests/
    ├── conftest.py                # testcontainers Postgres, migráció, tiny seed, fake LLM
    ├── unit/
    │   ├── text_to_sql/test_validator.py
    │   ├── eval/test_compare.py   # mikor ugyanaz a válasz; test_datasets.py: szivárgásőr
    │   ├── rag/test_chunking.py
    │   ├── agent/test_memory.py   # előzmény, összefoglalás; test_tools.py: eszközök, hibák
    │   ├── test_web.py            # az oldal, a CSP, nincs inline kód, nincs HTML-értelmezés
    │   └── …
    └── integration/
        ├── test_security.py       # RLS (saját fiók / minden fiók / kontextus nélkül 0 sor), írás, PII
        ├── test_analytics.py      # példakérdések, leírások teljessége, konzisztencia
        ├── test_readonly.py       # írás az llm_reader szerepkörrel → hiba
        ├── test_query_api.py
        ├── test_examples.py       # few-shot: sync, kiválasztás, prompt és napló
        ├── test_eval.py           # orákulum: 100%; szkriptelt válaszok bírálata
        ├── test_rag.py            # betöltés, hibrid keresés, olvasási szint, idézett válasz, napló
        └── test_agent.py          # SSE, eszközök, korlátok, memória, keret, zár, mérgezett dokumentum
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
