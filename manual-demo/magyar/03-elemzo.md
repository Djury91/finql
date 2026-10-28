# 3. Elemző Endre, elemző

[← Forgatókönyvek](README.md)

**Mit mutat meg:** az elemző az egész bank adatait látja, és a belső szabályzatokat is
olvashatja. Ugyanazok a kérdések, mint a fiókvezetőknél, banki szintű eredménnyel.

## Belépés

1. **Teendő:** a `<demó-cím>` oldalon (ha be vagy lépve, előbb **Kijelentkezés**) kattints az
   **Elemző Endre – elemző** gombra.

   **Elvárt:** jobb felül „Elemző Endre” és az *elemző* címke.

## Az egész bank

2. **Teendő:** kattints a **Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat
   szerint?** példakérdésre, majd nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:**
   - ugyanaz az SQL, mint a fiókvezetőknél;
   - `loans` = **18** (Pécs: 1, Budaörs: 2);
   - a válaszban: „Az adatbázis szerint (a bank összes fiókja): loans = 18.”
3. **Teendő:** **Új beszélgetés**, majd a **Hány aktív ügyfelünk van szegmensenként?**
   példakérdés. Nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:**

   | segment | customers |
   |---|---|
   | retail | 7659 |
   | premium | 1056 |
   | sme | 994 |
   | corporate | 210 |

## Összetett lekérdezés

4. **Teendő:** **Új beszélgetés**, írd be pontosan:
   `Melyik fiókban nőtt legjobban a kártyás költés negyedéves összevetésben?`
   (Ez a projektterv egyik példakérdése, ezért kulcs nélkül is van rá SQL.)
   Nyisd ki az *Adatbázis-lekérdezés* kártyát.

   **Elvárt:** egy `WITH` kifejezéssel és `LAG` ablakfüggvénnyel számoló SQL, az eredmény:

   | branch | quarter | growth_pct |
   |---|---|---|
   | Debreceni fiók | 2026-07-01 | 58,5 |
   | Békéscsabai fiók | 2026-07-01 | 21,9 |
   | Kaposvári fiók | 2026-07-01 | 15,3 |
   | Zalaegerszegi fiók | 2026-07-01 | 14 |
   | Kecskeméti fiók | 2026-07-01 | 13,5 |

   Alatta: „5 sor, a LIMIT levágta: lehet több is.”
5. **Teendő:** nézd meg a *Dokumentumkeresés* kártyát.

   **Elvárt:** az első találat a *Kártyacsalás-megelőzés – monitoring szabályok* belső
   szabályzat. A fiókvezetők ezt nem kapnák meg.

## Belső szabályzat: az elemző megtalálja

6. **Teendő:** **Új beszélgetés**, írd be: `Mekkora az NPL-ráta kemény limitje?`

   **Elvárt:** mindhárom találat a *Hitelportfólió-limitek és kockázati étvágy 2026* belső
   szabályzatból jön, az első a *Kockázati étvágy* szakasz. A válasz idézi: „NPL-ráta (90 napon
   túl késő hitelek tőketartozásának aránya): célérték 3% alatt, figyelmeztető szint 4%,
   kemény limit 5%.” Pécsi Péter ugyanerre a kérdésre nem kapta meg ezt a dokumentumot (1.
   forgatókönyv, 9. lépés).

## API (nem kötelező)

7. **Teendő:** a `<demó-cím>/docs` oldalon **Authorize**: `elemzo@minta-bank.example` és a közös
   jelszó. Utána `POST /query`, **Try it out**, a törzs:
   `{"question": "Hány aktív ügyfelünk van szegmensenként?"}`, majd **Execute**.

   **Elvárt:** `200`, `"status": "ok"`, a futtatott SQL, és ugyanaz a négy sor, mint a 3.
   lépésben. Az `explanation`: „Kézzel írt minta-SQL (ál-LLM, API-kulcs nélküli mód).”

[← Előző: Budaörsi Bea](02-budaorsi-fiokvezeto.md) · [Következő: Auditor Aliz →](04-auditor.md)
