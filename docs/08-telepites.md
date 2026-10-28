# 08 – Telepítés

A FinQL egy image-ből fut helyben (Docker Compose) és egy PaaS-on is. A döntések indoklása:
[ADR-011](02-technologiai-dontesek.md).

## 1. Az image

```bash
docker build -t finql .
```

- **Két lépcső:** az első uv-vel telepít a lock fájl szerint, a második csak a kész
  környezetet és a futáshoz kellő fájlokat kapja (`migrations/`, `db/`, `data/`). Mérete
  ~290 MB.
- **Nem root:** a folyamat a `finql` (10001) felhasználóval fut, a kód a root tulajdonában
  van, így a folyamat nem írhatja át.
- **Parancsok** (`docker/entrypoint.sh`):

| Parancs | Mit csinál |
|---|---|
| `serve` (alapértelmezett) | uvicorn a `PORT` porton (alapból 8000), proxy-fejlécekkel |
| `setup` | `finql db bootstrap` → `alembic upgrade head` → `finql seed --if-empty` → `finql user demo` → `finql ingest` → `finql examples sync` |
| bármi más | a megadott parancs, pl. `finql user create ...` |

A `setup` minden lépése idempotens: a második futás nem tölt be újra adatot, és csak a
változott dokumentumokat dolgozza fel. Ezért minden indításkor futhat.

- **Egészség:** `GET /health` (a folyamat él; az image `HEALTHCHECK`-je ezt nézi) és
  `GET /ready` (az adatbázis is válaszol; a PaaS ezt nézi telepítéskor).

## 2. Helyben: `docker compose up`

```bash
cp .env.example .env      # írd át a jelszavakat
docker compose up         # adatbázis → setup (~1,5 perc először) → http://127.0.0.1:8000
```

A Compose három szolgáltatást indít: `db` (pgvector/pgvector:pg18), `setup` (egyszer fut le),
`app` (csak a sikeres `setup` után indul). Az első indítás a `small` skálát tölti be (~2
millió tranzakció); a skálát a `FINQL_SEED_SCALE` állítja.

A konténerek ugyanazt a `.env`-et olvassák, mint a gépen futó alkalmazás. A konténerből az
adatbázis a `db` néven érhető el, nem a `127.0.0.1`-en: az entrypoint a `FINQL_DB_HOST`
alapján cseréli a hosztot az URL-ekben, így a jelszavak egy helyen maradnak.

**Kulcs nélkül** (a `.env.example` alapértéke: `FINQL_LLM_PROVIDER=fake`,
`FINQL_EMBEDDING_PROVIDER=hashing`) a teljes felület kipróbálható. Az adatkérdések közül csak a
projektterv példakérdéseire felel, a dokumentumkeresés lexikális. **Claude-dal:**
`FINQL_LLM_PROVIDER=anthropic`, `FINQL_ANTHROPIC_API_KEY`, és ajánlott a Voyage is
(`FINQL_EMBEDDING_PROVIDER=voyage`, `FINQL_VOYAGE_API_KEY`). Utána
`docker compose up -d --force-recreate setup app`: a `setup` újra-embeddingeli a
dokumentumokat az új modellel.

## 3. PaaS: Railway

A [`railway.json`](../railway.json) írja le az alkalmazásszolgáltatást: a `Dockerfile`-ból
épül, telepítés előtt lefut a `setup` (pre-deploy), és a `/ready` dönti el, hogy az új
változat élesbe állhat-e.

**Miért a saját Postgres-image:** a `setup` szerepköröket hoz létre (`CREATE ROLE`), és a
`vector` bővítményt telepíti. Ehhez superuser kell, amit a menedzselt Postgres-szolgáltatások
többsége nem ad, és a PG18 sem mindenhol elérhető. A Railway-en egy Docker-image
szolgáltatásként fut, kötettel, ugyanaz az image, mint helyben és a CI-ban.

### Lépések

1. **Projekt:** Railway → *New Project* → *Deploy from GitHub repo* → ez a repó. Ez lesz az
   `app` szolgáltatás (a `railway.json` szerint).
2. **Adatbázis:** *New* → *Docker Image* → `pgvector/pgvector:pg18`, a neve legyen `db`.
   - Kötet: *Add Volume*, csatolási pont: `/var/lib/postgresql`.
   - Változók: `POSTGRES_PASSWORD` (erős, véletlen), `POSTGRES_DB=finql`.
   - Publikus hálózat nem kell: az `app` a privát hálózaton éri el (`db.railway.internal`).
3. **Az `app` változói** (*Variables*). A jelszavak legyenek erősek és különbözők; a `setup`
   ezekből állítja be a szerepkörök jelszavát:

```
FINQL_ENV=prod
FINQL_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:<POSTGRES_PASSWORD>@db.railway.internal:5432/finql
FINQL_MIGRATION_DATABASE_URL=postgresql+psycopg://finql_migrator:<jelszó1>@db.railway.internal:5432/finql
FINQL_DATABASE_URL=postgresql+asyncpg://finql_app:<jelszó2>@db.railway.internal:5432/finql
FINQL_LLM_DATABASE_URL=postgresql+asyncpg://finql_llm_reader:<jelszó3>@db.railway.internal:5432/finql
FINQL_JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">
FINQL_DEMO_PASSWORD=<a demófelhasználók jelszava>
FINQL_LLM_PROVIDER=fake
FINQL_EMBEDDING_PROVIDER=hashing
FINQL_PUBLIC_DEMO=true
```

   Nyomkövetés (opcionális, ADR-014): `FINQL_OTEL_ENDPOINT` egy OTLP/HTTP-gyűjtő címe (pl. egy
   menedzselt OpenTelemetry-szolgáltatás). Üresen ki van kapcsolva.

4. **Domain:** az `app` → *Settings* → *Networking* → *Generate Domain*. A `PORT` változót a
   Railway adja, az entrypoint azon indítja az uvicornt.
5. **Ellenőrzés:** `https://<domain>/ready` → `{"status":"ready","database":"ok"}`, és a
   főoldalon a bejelentkezés. Utána a belépőoldalról linkelt demó-forgatókönyvek
   (`https://<domain>/forgatokonyvek/`, forrásuk a `manual-demo/magyar/`) lépésről lépésre
   végigvihetők; az elvárt számok minden telepítésben ugyanazok.

### Nyilvános demó: költség és visszaélés

Nyilvános demónál a demófelhasználók jelszava is nyilvános. Valódi API-kulccsal így bárki a
bank nevében költhetne tokent, felhasználónként a napi keretig (alapból 200 000 token), és
mind az öt demófelhasználóval.

- **Ajánlott:** kulcs nélküli mód (`FINQL_LLM_PROVIDER=fake`): nincs költség, a felület,
  a jogosultságok és a stream valódi.
- **Claude-dal:** a jelszót csak annak add meg, akinek szánod, és csökkentsd a keretet
  (`app.users.daily_token_budget`). Az Anthropic-konzolon állíts költési limitet a kulcsra.

**`FINQL_PUBLIC_DEMO=true`:** a belépőoldal szerepkörönként egy gombot mutat, amely egy
kattintással belép, és kiírja a közös jelszót az API-hoz. Kulcs nélkül a jelszó nem véd
semmit (az adat kitalált, nincs mit elkölteni), ezért nem kezeljük titokként; ami a rendszert
védi, az a Row-Level Security és a validált SQL. A beállítás csak `FINQL_LLM_PROVIDER=fake` és
`FINQL_EMBEDDING_PROVIDER=hashing` mellett indul el: fizetős kulccsal az alkalmazás és a `setup`
is hibával áll meg, így nyilvános jelszó mellé nem kerülhet költség.

Egy ismert korlát: a beszélgetések felhasználóhoz tartoznak, így az ugyanazzal a
demófelhasználóval belépők látják egymás korábbi kérdéseit. A `messages` napló szándékosan csak
hozzáfűzhető, ezért ezt törléssel nem oldjuk meg.

### Más platformon

Bármely platform jó, amely Docker-image-et futtat, és ad egy pre-deploy (release) lépést vagy
egyszer futó feladatot:

- **Fly.io:** `fly launch` a `Dockerfile`-ból, a `[deploy] release_command =
  "finql-entrypoint setup"`; a Postgres egy második Fly-alkalmazásként, ugyanazzal a
  `pgvector/pgvector:pg18` image-dzsel és egy kötettel.
- **Render:** web service a `Dockerfile`-ból, *Pre-Deploy Command*: `finql-entrypoint setup`.
  A Postgres egy privát szolgáltatás (`pgvector/pgvector:pg18`) lemezzel; a lemez fizetős
  csomagot kíván.

A menedzselt Postgres (Neon, Supabase, Render Postgres) akkor használható, ha a szerepköröket
és a `vector` bővítményt egyszer kézzel, adminként létrehozod (`db/roles/`,
`db/extensions/`). Ilyenkor a `FINQL_ADMIN_DATABASE_URL` maradjon üresen: a `setup` ezt a
lépést kihagyja.
