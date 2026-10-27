#!/bin/sh
# A konténer parancsai:
#   serve  az API és a webes felület (uvicorn), a PORT változó portján (alapból 8000)
#   setup  az adatbázis előkészítése: szerepkörök, migrációk, banki adatok (ha még nincsenek),
#          demófelhasználók, dokumentumok, few-shot példák. Minden lépése idempotens, így minden
#          indításkor futhat.
# Bármi más: a megadott parancs fut (pl. `finql user create ...`).
set -eu

# A Compose a .env URL-jeit használja (egy helyen a jelszavak), de a konténerből az adatbázis
# nem a 127.0.0.1-en, hanem a hálózat `db` nevén érhető el. FINQL_DB_HOST=db:5432 esetén a négy
# URL hoszt:port része erre cserélődik. PaaS-on az URL-ek eleve jók, ott ez üres.
if [ -n "${FINQL_DB_HOST:-}" ]; then
    for name in FINQL_DATABASE_URL FINQL_LLM_DATABASE_URL FINQL_MIGRATION_DATABASE_URL \
        FINQL_ADMIN_DATABASE_URL; do
        value=$(printenv "$name" || true)
        if [ -n "$value" ]; then
            export "$name=$(printf '%s' "$value" | sed -E "s#@[^@/]+/#@${FINQL_DB_HOST}/#")"
        fi
    done
fi

case "${1:-serve}" in
    serve)
        # A proxy (PaaS) mögött az X-Forwarded-* fejlécekből jön a kliens címe és a séma.
        exec uvicorn finql.main:create_app --factory \
            --host 0.0.0.0 --port "${PORT:-8000}" \
            --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
            --no-server-header
        ;;
    setup)
        if [ -n "${FINQL_ADMIN_DATABASE_URL:-}" ]; then
            finql db bootstrap
        else
            echo "FINQL_ADMIN_DATABASE_URL nélkül a szerepkörök előkészítése kimarad."
        fi
        alembic upgrade head
        finql seed --scale "${FINQL_SEED_SCALE:-small}" --if-empty
        if [ -n "${FINQL_DEMO_PASSWORD:-}" ]; then
            finql user demo
        fi
        finql ingest
        if [ "${FINQL_FEW_SHOT_K:-3}" != "0" ]; then
            finql examples sync
        fi
        echo "Az adatbázis kész."
        ;;
    *)
        exec "$@"
        ;;
esac
