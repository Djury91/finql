# 1. Pécsi Péter, fiókvezető

[← Forgatókönyvek](README.md)

**Mit mutat meg:** a fiókvezető csak a saját fiókja (PEC01, Pécs) adatait látja, és csak az
általános szabályzatokat olvashatja. A szűrést az adatbázis végzi (Row-Level Security): a
generált SQL-ben nincs fiókszűrés.

## Belépés

1. **Teendő:** nyisd meg a `<demó-cím>` oldalt.

   **Elvárt:** felül sárga sáv („Demó mód, API-kulcs nélkül…”), középen a *Bejelentkezés*
   kártya, alatta öt gomb: Pécsi Péter, Budaörsi Bea, Elemző Endre, Auditor Aliz, Admin Anna.
2. **Teendő:** kattints a **Pécsi Péter – fiókvezető (PEC01)** gombra.

   **Elvárt:** jobb felül „Pécsi Péter” és a *fiókvezető* címke. Középen „Kérdezz az adatokról
   vagy a szabályzatokról”, alatta négy példakérdés-gomb.

## Adatkérdés és szabályzat: csak a saját fiók

3. **Teendő:** kattints a **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat
   szerint?** példakérdésre.

   **Elvárt:** a kérdésed jobbra kerül. A válaszban két eszközkártya jelenik meg, mindkettő
   zöld időértékkel (*… ms*):
   - *Adatbázis-lekérdezés* – „Hány 90+ napos késedelmes hitelünk van?”
   - *Dokumentumkeresés* – a teljes kérdés
4. **Teendő:** kattints az *Adatbázis-lekérdezés* kártyára.

   **Elvárt:** a futtatott SQL és az eredmény:
   ```sql
   SELECT
     COUNT(*) AS loans
   FROM loans
   WHERE
     dpd_bucket = '90+'
   LIMIT 200
   ```
   A táblázatban `loans` = **1**, alatta „1 sor. Napló: #…”.
   Figyeld meg: az SQL-ben nincs fiókszűrés, mégis csak a pécsi hiteleket számolta meg.
5. **Teendő:** olvasd el a válasz szövegét.

   **Elvárt:**
   - „API-kulcs nélküli mód: ezt a választ nem nyelvi modell írta, az eszközök eredményét idézi.”
   - „Az adatbázis szerint (csak a felhasználó saját fiókja (branch_id = 3)): loans = 1.”
   - Egy idézet a *Követeléskezelési szabályzat – késedelmes hitelek* dokumentumból, a végén [1].
6. **Teendő:** kattints a *Dokumentumkeresés* kártyára.

   **Elvárt:** három találat, mind a *Követeléskezelési szabályzat – késedelmes hitelek*
   dokumentumból; a [2] szakasza „90 napon túli késedelem”, a [3]-é „61–90 napos késedelem”.
7. **Teendő:** kattints a válasz alján a forrásra: **Követeléskezelési szabályzat – késedelmes
   hitelek** (hatályos: 2026-03-01).

   **Elvárt:** kinyílik az idézett szövegrész.

## Szegmensek: csak a saját fiók ügyfelei

8. **Teendő:** bal felül **Új beszélgetés**, majd a **Hány aktív ügyfelünk van
   szegmensenként?** példakérdés. Nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:** négysoros táblázat:

   | segment | customers |
   |---|---|
   | retail | 340 |
   | premium | 50 |
   | sme | 47 |
   | corporate | 10 |

   A *Dokumentumkeresés* első találata az *Üzleti fogalomtár és mutatók – Ügyfelek és
   szegmensek*, a válasz az aktív ügyfél definícióját idézi belőle.

## Belső szabályzat: a fiókvezető nem találja

9. **Teendő:** **Új beszélgetés**, írd be a mezőbe: `Mekkora az NPL-ráta kemény limitje?`,
   majd nyomj Entert.

   **Elvárt:** csak *Dokumentumkeresés* kártya van, adatbázis-lekérdezés nincs (ez nem
   adatkérdés). A három találat:
   - [1] Üzleti fogalomtár és mutatók – Hitelek és késedelem
   - [2] Pénztári műveletek és készpénzkezelés a fiókban – Hamis vagy gyanús bankjegy
   - [3] Ügyfél-átvilágítás és a pénzmosás megelőzése – Az átvilágítás lépései

   A válasz a fogalomtárat idézi, a limitet nem mondja meg. A választ tartalmazó
   *Hitelportfólió-limitek és kockázati étvágy 2026* belső szabályzat, a fiókvezető nem
   olvashatja, ezért a keresés nem is adja vissza. Ugyanez a kérdés az elemzőnek megtalálja (3. forgatókönyv, 6.
   lépés).

## Szabad kérdés kulcs nélkül

10. **Teendő:** **Új beszélgetés**, írd be: `Melyik ügyfelünknek van a legtöbb pénze?`

    **Elvárt:** csak *Dokumentumkeresés* fut, adatbázis-lekérdezés nem. Kulcs nélkül az
    adatkérdések közül csak a példakérdésekre van kézzel írt SQL; szabad kérdéshez Claude kell.

## API (nem kötelező)

11. **Teendő:** nyisd meg a `<demó-cím>/docs` oldalt, kattints az **Authorize** gombra.
    *username*: `pecs@minta-bank.example`, *password*: a belépőoldal alján kiírt közös jelszó.
    **Authorize**, majd **Close**.

    **Elvárt:** a lakatok bezárt állapotra váltanak.
12. **Teendő:** `GET /query/history` → **Try it out** → **Execute**.

    **Elvárt:** `200`, a saját korábbi kérdéseid; minden sorban `"scope": "branch"` és
    `"branch_id": 3`.
13. **Teendő:** `GET /audit/queries` → **Try it out** → **Execute**.

    **Elvárt:** `403`, „Ehhez a művelethez nincs jogosultságod.” A naplót csak az auditor és az
    admin olvashatja.

[Következő: Budaörsi Bea →](02-budaorsi-fiokvezeto.md)
