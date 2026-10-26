-- Könyvelt tranzakciók, havi particionálással (booked_at szerint, budapesti naptári hónapok).
--
-- Miért particionálás? A lekérdezések szinte mindig időszakra szűrnek. A partition pruning miatt
-- egy havi kérdés egyetlen partíciót olvas, a régi hónapok pedig egyben archiválhatók vagy
-- törölhetők (DETACH / DROP) DELETE nélkül.

CREATE TABLE bank.transactions (
    -- Identity particionált táblán: PostgreSQL 17 óta támogatott.
    transaction_id  bigint          GENERATED ALWAYS AS IDENTITY,
    booked_at       timestamptz     NOT NULL,
    account_id      bigint          NOT NULL,
    -- Szándékos denormalizálás: az RLS és a fiókszintű szűrés JOIN nélkül működik.
    -- Az összetett FK garantálja, hogy egyezik a számla fiókjával.
    branch_id       int             NOT NULL,
    card_id         bigint          REFERENCES bank.cards,
    merchant_id     bigint          REFERENCES bank.merchants,
    amount          numeric(18, 2)  NOT NULL CHECK (amount <> 0),  -- előjeles: + jóváírás, − terhelés
    currency        char(3)         NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    channel         bank.tx_channel NOT NULL,
    description     text,

    -- Particionált táblán a PK-nak tartalmaznia kell a partíciókulcsot.
    PRIMARY KEY (transaction_id, booked_at),
    CONSTRAINT transactions_account_branch_fk
        FOREIGN KEY (account_id, branch_id) REFERENCES bank.accounts (account_id, branch_id)
        ON UPDATE CASCADE,
    CONSTRAINT transactions_card_ck CHECK (card_id IS NULL OR channel IN ('card', 'atm'))
) PARTITION BY RANGE (booked_at);

-- Ide kerül minden, amire még nincs havi partíció. Üresen kell maradnia: ha sor kerül bele,
-- az adott hónapra már nem hozható létre partíció, amíg a sorokat át nem mozgatjuk.
CREATE TABLE bank.transactions_default PARTITION OF bank.transactions DEFAULT;

-- Havi partíciók létrehozása [p_from, p_to] hónapjaira (a napot figyelmen kívül hagyja).
-- A határok budapesti éjfélek, így a hónap a magyar naptár szerinti hónap, téli és nyári
-- időszámításban is. Idempotens: a meglévő partíciót kihagyja. Visszatérés: új partíciók száma.
CREATE FUNCTION bank.create_transaction_partitions(p_from date, p_to date)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
    v_month    date := date_trunc('month', p_from)::date;
    v_last     date := date_trunc('month', p_to)::date;
    v_name     text;
    v_created  int  := 0;
BEGIN
    WHILE v_month <= v_last LOOP
        v_name := format('transactions_%s', to_char(v_month, 'YYYY_MM'));
        IF to_regclass(format('bank.%I', v_name)) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE bank.%I PARTITION OF bank.transactions FOR VALUES FROM (%L) TO (%L)',
                v_name,
                make_timestamptz(extract(year FROM v_month)::int, extract(month FROM v_month)::int,
                                 1, 0, 0, 0, 'Europe/Budapest'),
                make_timestamptz(extract(year FROM v_month + interval '1 month')::int,
                                 extract(month FROM v_month + interval '1 month')::int,
                                 1, 0, 0, 0, 'Europe/Budapest')
            );
            v_created := v_created + 1;
        END IF;
        v_month := (v_month + interval '1 month')::date;
    END LOOP;
    RETURN v_created;
END
$$;

REVOKE EXECUTE ON FUNCTION bank.create_transaction_partitions(date, date) FROM PUBLIC;

COMMENT ON FUNCTION bank.create_transaction_partitions(date, date) IS
    'Havi partíciók létrehozása a bank.transactions táblához (budapesti hónaphatárokkal). Idempotens.';
