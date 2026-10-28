# 2. Budaörsi Bea, fiókvezető

[← Forgatókönyvek](README.md)

**Mit mutat meg:** ugyanaz a kérdés ugyanazt az SQL-t futtatja, mint Pécsi Péternél, de más
eredményt ad, mert Budaörsi Bea a budaörsi fiók (BUO01) fiókvezetője. A különbséget az
adatbázis jogosultsági szabályai adják, nem az SQL.

## Belépés

1. **Teendő:** a `<demó-cím>` oldalon (ha be vagy lépve, előbb jobb felül **Kijelentkezés**)
   kattints a **Budaörsi Bea – fiókvezető (BUO01)** gombra.

   **Elvárt:** jobb felül „Budaörsi Bea” és a *fiókvezető* címke.

## Ugyanaz a kérdés, más fiók

2. **Teendő:** kattints a **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat
   szerint?** példakérdésre, majd nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:**
   - az SQL betűre ugyanaz, mint az 1. forgatókönyv 4. lépésében;
   - a táblázatban `loans` = **2** (Pécsen 1 volt);
   - a válaszban: „Az adatbázis szerint (csak a felhasználó saját fiókja (branch_id = 2)):
     loans = 2.”
3. **Teendő:** **Új beszélgetés**, majd a **Hány aktív ügyfelünk van szegmensenként?**
   példakérdés. Nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:** a budaörsi ügyfelek, a pécsiektől eltérő számokkal:

   | segment | customers |
   |---|---|
   | retail | 438 |
   | sme | 57 |
   | premium | 53 |
   | corporate | 13 |

## Más felhasználó beszélgetései

4. **Teendő:** nézd meg a bal oldali beszélgetéslistát.

   **Elvárt:** csak Budaörsi Bea beszélgetései vannak benne; Pécsi Péter kérdései nem
   látszanak, akkor sem, ha az előbb ugyanabban a böngészőben te tetted fel őket.

[← Előző: Pécsi Péter](01-pecsi-fiokvezeto.md) · [Következő: Elemző Endre →](03-elemzo.md)
