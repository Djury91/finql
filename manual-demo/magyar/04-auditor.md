# 4. Auditor Aliz, auditor

[← Forgatókönyvek](README.md)

**Mit mutat meg:** az auditor banki adatot nem lát, ezért adatbázis-eszközt sem kap. A
szabályzatokat, a belsőket is, olvashatja, és ő ellenőrzi a naplót: ki mit kérdezett, milyen
SQL futott, és nem írta-e át valaki utólag a naplót.

## Belépés

1. **Teendő:** a `<demó-cím>` oldalon (ha be vagy lépve, előbb **Kijelentkezés**) kattints az
   **Auditor Aliz – auditor** gombra.

   **Elvárt:** jobb felül „Auditor Aliz” és az *auditor* címke.

## Adatkérdés: nincs adatbázis-eszköz

2. **Teendő:** kattints a **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat
   szerint?** példakérdésre.

   **Elvárt:** csak *Dokumentumkeresés* kártya van, *Adatbázis-lekérdezés* nincs. A válaszban
   nincs „Az adatbázis szerint…” sor, csak a *Követeléskezelési szabályzat* idézete. Ugyanez a
   kérdés a fiókvezetőnek és az elemzőnek számot is adott.

## Belső szabályzat

3. **Teendő:** **Új beszélgetés**, írd be: `Mekkora az NPL-ráta kemény limitje?`

   **Elvárt:** a találatok a *Hitelportfólió-limitek és kockázati étvágy 2026* belső
   szabályzatból jönnek, a válasz idézi: „… kemény limit 5%.”

## Napló (API)

A naplót a felület nem mutatja, az API-n keresztül érhető el.

4. **Teendő:** nyisd meg a `<demó-cím>/docs` oldalt, **Authorize**:
   `auditor@minta-bank.example` és a belépőoldal alján kiírt közös jelszó.
5. **Teendő:** `POST /query`, **Try it out**, a törzs:
   `{"question": "Hány aktív ügyfelünk van szegmensenként?"}`, **Execute**.

   **Elvárt:** `403`, „Ehhez a művelethez nincs jogosultságod.” Az auditor az API-n át sem
   kérdezhet banki adatot.
6. **Teendő:** `GET /audit/queries` → **Try it out** → **Execute**.

   **Elvárt:** `200`, minden felhasználó lekérdezései, a legfrissebb elöl. Soronként többek
   között: `user_id`, `scope` (`branch` a fiókvezetőknél, `all` az elemzőnél és az adminnál),
   `branch_id`, `question`, `generated_sql`, `executed_sql`, `status`. Ha előtte végigvitted az
   1–3. forgatókönyvet, a kérdéseid itt vannak.
7. **Teendő:** `GET /audit/chain` → **Try it out** → **Execute**.

   **Elvárt:** `200`, két elem: `"log": "query_log"` és `"log": "answer_log"`, mindkettőnél
   `"intact": true` és `"broken_at": null`. A `checked` mondja meg, hány sort ellenőrzött; a
   `head_hash` a lánc utolsó elemének hash-e. Egy utólag átírt, törölt vagy beszúrt naplósor
   itt `"intact": false`-t adna, a hibás sor sorszámával.

[← Előző: Elemző Endre](03-elemzo.md) · [Következő: Admin Anna →](05-admin.md)
