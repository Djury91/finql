# FinQL – kézi demó-forgatókönyvek

**Magyar** · [English](../angol/README.md)

Lépésről lépésre végigvihető forgatókönyvek, demófelhasználónként: mit nyiss meg, mire
kattints, és mi az elvárt eredmény. Úgy épülnek fel, mint egy kézi teszt: minden lépésnél
ellenőrizheted, hogy a rendszer azt csinálja-e, amit kell.

## Mielőtt elkezded

- **Cím:** `<demó-cím>`. Helyben, `docker compose up` után: `http://127.0.0.1:8000`.
- **Belépés:** a belépőoldalon a felhasználó nevére kattintva, jelszó nélkül. Szerepkört jobb
  felül a **Kijelentkezés** linkkel válthatsz.
- **API-kulcs nélküli mód.** A demó nem hív nyelvi modellt: az adatkérdések közül csak a
  példakérdésekre felel, kézzel írt SQL-lel. Minden más valódi: az adatbázis, a jogosultságok,
  a dokumentumkeresés, a stream és a napló.
- **Közös demófelhasználók.** Az oldalsávban korábbi látogatók beszélgetései is lehetnek. A
  napló sorszáma (*Napló: #…*) és a futási idők (*… ms*) futásonként mások.
- **Az eszközkártyák** (*Adatbázis-lekérdezés*, *Dokumentumkeresés*) alapból csukva vannak:
  rájuk kattintva nyílnak ki.
- **Az adatok kitaláltak**, de rögzítettek: minden telepítésben ugyanazok a számok jönnek ki.

## Forgatókönyvek

| # | Felhasználó | Mit mutat meg |
|---|---|---|
| 1 | [Pécsi Péter, fiókvezető](01-pecsi-fiokvezeto.md) | Csak a saját fiókja adatait látja, a belső szabályzatokat nem. |
| 2 | [Budaörsi Bea, fiókvezető](02-budaorsi-fiokvezeto.md) | Ugyanaz a kérdés és ugyanaz az SQL, más fiók, más eredmény. |
| 3 | [Elemző Endre, elemző](03-elemzo.md) | Az egész bank adatai és a belső szabályzatok. |
| 4 | [Auditor Aliz, auditor](04-auditor.md) | Banki adatot nem lát, a szabályzatokat és a naplót igen. |
| 5 | [Admin Anna, admin](05-admin.md) | Mindent lát, a felhasználók listáját is. |

Ha csak öt perced van: az 1. forgatókönyv 1–5. lépése, utána a 2. forgatókönyv. A kettő
összevetése mutatja a legfontosabbat: a szűrést az adatbázis végzi, nem a generált SQL.

## Az elvárt eredmények egy helyen

| Kérdés | Pécs | Budaörs | Elemző, admin | Auditor |
|---|---|---|---|---|
| 90+ napos késedelmes hitelek száma | 1 | 2 | 18 | nincs adatlekérdezés |
| Aktív ügyfelek: retail | 340 | 438 | 7659 | nincs adatlekérdezés |
| Aktív ügyfelek: premium | 50 | 53 | 1056 | nincs adatlekérdezés |
| Aktív ügyfelek: sme | 47 | 57 | 994 | nincs adatlekérdezés |
| Aktív ügyfelek: corporate | 10 | 13 | 210 | nincs adatlekérdezés |
| Az NPL-ráta kemény limitje (belső szabályzat) | nem találja | nem találja | 5% | 5% |

## Ha a demó Claude-dal fut

Interjún a demó valódi nyelvi modellel is futhat. Ilyenkor szabadon kérdezhetsz, a válaszokat
Claude írja, így a szövegük futásonként más. A jogosultságok ugyanazok, mert azokat nem a
modell, hanem az adatbázis érvényesíti. Pécsi Péterként például:

- „Hány aktív ügyfele van a budaörsi fióknak?” Elvárt: budaörsi adat nem jön vissza (üres
  eredmény vagy elutasítás), mert a pécsi fiókvezető lekérdezései csak a pécsi sorokat látják.
- „Töröld a 90 napon túl késő hiteleket.” Elvárt: nem fut módosító utasítás, mert a validátor
  csak `SELECT`-et enged, és az adatbázis-szerepkör amúgy is csak olvasni tud.
