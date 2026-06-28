# ✈️ Szukacz tanich lotów → Discord + strona

Skanuje **Ryanair + Wizz Air** z **Katowic (KTW)**, filtruje po cenie i długości
pobytu, dorzuca link do **hotelu (Booking, 4 os., daty pobytu)** i:
- wysyła **nowe** oferty na kanał Discord (bez spamu — pamięta wysłane),
- zapisuje pełną listę do `deals.json`, którą czyta **strona** (`index.html`)
  z mapą i filtrami.

Tylko Python 3 (stdlib, zero `pip install`).

## Pliki

| Plik | Co to |
|------|-------|
| `dealfinder.py` | skrypt — pobiera loty, wysyła Discord, generuje `deals.json` |
| `index.html` | strona z mapą + listą okazji (czyta `deals.json`) |
| `deals.json` | wynik ostatniego skanu (auto) |
| `seen.json` | dedup — już wysłane na Discord (auto, nie ruszaj) |

## 1. Discord webhook (2 min)

Discord → ustawienia kanału ⚙️ → **Integracje → Webhooki → Nowy webhook** →
skopiuj **URL**. Ustaw jako zmienną środowiskową:

**Linux/Mac:** `export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."`
**Windows PS:** `$env:DISCORD_WEBHOOK = "https://discord.com/api/webhooks/..."`

Bez webhooka skrypt tylko wypisze oferty na ekran (do testów).

## 2. Proxy dla Wizz (wymagane dla Wizz, opcjonalne ogólnie)

Wizz blokuje boty (Incapsula) → potrzebne proxy. Plik z listą w formacie
`ip:port:user:pass` (po jednym na linię). Ścieżkę ustaw w `CONFIG['proxy_file']`
albo zmienną `PROXY_FILE`. Brak proxy = Wizz pominięty, Ryanair działa dalej.

> ⚠️ Wizz API jest kruche: **wersja API zmienia się co tydzień** (skrypt
> wykrywa ją automatycznie z homepage), a anty-bot bywa agresywny. Jak Wizz
> przestanie zwracać oferty — to zwykle wersja/proxy. Ryanair jest stabilny.

## 3. Uruchomienie ręczne

```bash
python dealfinder.py
```
Pierwszy bieg trwa kilka minut (skan ~41 tras Wizz po kawałkach dat).

## 4. Konfiguracja — słownik `CONFIG` na górze `dealfinder.py`

| Pole | Co robi |
|------|---------|
| `origin` | lotnisko startowe (IATA), domyślnie `KTW` |
| `max_price_pln` | maks. cena za osobę za lot tam i z powrotem |
| `nights_from`/`nights_to` | długość pobytu (noce) |
| `lead_days`/`window_days` | okno dat: od dziś+lead przez window dni |
| `pax` | ile osób (cena łączna + Booking dla tylu osób) |
| `only_countries` | filtr krajów, np. `["Italy","Spain"]`; puste = wszystkie |
| `enable_wizz` | `False` = tylko Ryanair |

## 5. Strona (mapa + filtry)

`index.html` czyta `deals.json` przez `fetch` → **musi być serwowana po HTTP**
(otwarcie pliku `file://` zablokuje fetch).

**Lokalnie:**
```bash
cd loty && python -m http.server 8123
# otwórz http://localhost:8123
```

**GitHub Pages (publiczny adres):** wrzuć `index.html` + `deals.json` do repo z
Pages. Cron na serwerze po każdym skanie commituje świeży `deals.json`:
```bash
0 */6 * * * cd /sciezka/loty && DISCORD_WEBHOOK="..." python3 dealfinder.py && git commit -am "deals $(date +\%F)" && git push
```

## 6. Automat na serwerze

### Linux (cron) — co 6 h
```cron
0 */6 * * * DISCORD_WEBHOOK="https://discord.com/api/webhooks/..." PROXY_FILE="/sciezka/proxy.txt" /usr/bin/python3 /sciezka/loty/dealfinder.py >> /sciezka/loty/run.log 2>&1
```

### Windows (Harmonogram zadań)
```powershell
setx DISCORD_WEBHOOK "https://discord.com/api/webhooks/..."
schtasks /create /tn "SzukaczLotow" /tr "python C:\Users\Redix\Documents\loty\dealfinder.py" /sc hourly /mo 6
```

## ⚠️ Ważne dla ekipy 17/18 lat

- **Loty:** Ryanair i Wizz pozwalają 16+ lecieć bez opiekuna. OK.
- **Hotele/hostele:** często wymagają **18+ przy zameldowaniu**. Część obiektów
  chce żeby KAŻDY gość był pełnoletni. **Sprawdzajcie zasady obiektu przed
  rezerwacją** — realne ryzyko że nie wpuszczą. Linki Booking w ofertach mają
  już ustawione 4 osoby i daty pobytu — filtrujcie po „bez limitu wieku".

## Pomysły na v3

- Więcej lotnisk startowych naraz (KRK, WAW).
- easyJet / Lufthansa Group (trudniejsze API).
- Powiadomienie tylko gdy cena spadnie poniżej progu (tracking historii cen).
