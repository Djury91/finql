# 5. Admin Anna, admin

[← Forgatókönyvek](README.md)

**Mit mutat meg:** az admin az egész bank adatait látja, minden szabályzatot olvashat, a naplót
ellenőrizheti, és egyedül ő láthatja a felhasználók listáját.

## Belépés

1. **Teendő:** a `<demó-cím>` oldalon (ha be vagy lépve, előbb **Kijelentkezés**) kattints az
   **Admin Anna – admin** gombra.

   **Elvárt:** jobb felül „Admin Anna” és az *admin* címke.

## Adatkérdés

2. **Teendő:** kattints a **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat
   szerint?** példakérdésre, majd nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:** `loans` = **18**, mint az elemzőnél; a válaszban „(a bank összes fiókja)”.

## Felhasználók és napló (API)

3. **Teendő:** a `<demó-cím>/docs` oldalon **Authorize**: `admin@minta-bank.example` és a közös
   jelszó.
4. **Teendő:** `GET /auth/users` → **Try it out** → **Execute**.

   **Elvárt:** `200`, öt felhasználó: `admin@`, `auditor@`, `budaors@`, `elemzo@` és
   `pecs@minta-bank.example`, a szerepkörükkel (`admin`, `auditor`, `branch_manager`,
   `analyst`). Jelszó vagy jelszó-hash nincs a válaszban.
5. **Teendő:** ugyanez Pécsi Péterként (**Logout**, majd **Authorize** a `pecs@` címmel).

   **Elvárt:** `403`, „Ehhez a művelethez nincs jogosultságod.”
6. **Teendő:** adminként `GET /audit/chain`.

   **Elvárt:** `200`, mindkét napló `"intact": true`, mint az auditornál.

[← Előző: Auditor Aliz](04-auditor.md) · [Vissza a forgatókönyvekhez](README.md)
