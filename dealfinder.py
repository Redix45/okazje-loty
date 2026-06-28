#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Szukacz tanich lotow (Ryanair + Wizz Air) -> Discord + deals.json (strona).
Tylko stdlib. Wizz wymaga proxy (anty-bot) — patrz CONFIG['proxy_file'].

Uruchom: python dealfinder.py
Cron: patrz README.md
"""

import json
import os
import sys
import time
import random
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────── KONFIG ───────────────────────────
CONFIG = {
    "origin": "KTW",                 # lotnisko startowe (IATA)
    "max_price_pln": 300,            # maks. cena za osobe za lot tam+powrot
    "nights_from": 2,
    "nights_to": 5,
    "date_from": None,               # None = dzis + lead_days
    "date_to": None,                 # None = date_from + window_days
    "lead_days": 7,
    "window_days": 90,
    "pax": 4,                        # ile osob (cena laczna + hotel + Booking)
    "only_countries": [],            # np. ["Italy","Spain"]; puste = wszystkie

    "discord_webhook": os.environ.get("DISCORD_WEBHOOK", ""),
    "seen_file": os.path.join(HERE, "seen.json"),
    "deals_out": os.path.join(HERE, "deals.json"),   # czyta strona

    # Wizz: lista proxy (format ip:port:user:pass na linie). Pusty = pomin Wizz.
    "proxy_file": os.environ.get("PROXY_FILE",
                                 r"C:\Users\Redix\Desktop\Egzaminy\Webshare 100 proxies.txt"),
    "enable_wizz": True,
    "wizz_max_routes": 41,           # ile tras z KTW skanowac (bezpiecznik)
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RYANAIR_API = "https://services-api.ryanair.com/farfnd/v4/roundTripFares"
RYANAIR_LIMIT = 16

WIZZ_COORDS = {}   # iata -> (lat, lon, city, country); do backfillu mapy Ryanair


# ─────────────────────────── POMOCNICZE ───────────────────────────
def daterange():
    df = CONFIG["date_from"]
    dt = CONFIG["date_to"]
    if not df:
        df = (date.today() + timedelta(days=CONFIG["lead_days"])).isoformat()
    if not dt:
        dt = (date.fromisoformat(df) + timedelta(days=CONFIG["window_days"])).isoformat()
    return df, dt


def load_proxies():
    try:
        raw = open(CONFIG["proxy_file"], encoding="utf-8").read().split()
    except Exception:
        return []
    out = []
    for line in raw:
        parts = line.strip().split(":")
        if len(parts) == 4:
            ip, port, u, pw = parts
            out.append(f"http://{u}:{pw}@{ip}:{port}")
    return out


def opener_for(proxy_url):
    if proxy_url:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return urllib.request.build_opener()


def booking_link(deal):
    """Deep-link Booking: miasto + daty pobytu + liczba osob."""
    ci = deal["out_date"][:10]
    co = deal["in_date"][:10]
    q = urllib.parse.urlencode({
        "ss": f"{deal['city']}, {deal['country']}",
        "checkin": ci, "checkout": co,
        "group_adults": CONFIG["pax"], "no_rooms": 1, "group_children": 0,
    })
    return "https://www.booking.com/searchresults.html?" + q


# ─────────────────────────── RYANAIR ───────────────────────────
def _ry_page(df, dt, offset):
    p = {
        "departureAirportIataCode": CONFIG["origin"],
        "outboundDepartureDateFrom": df, "outboundDepartureDateTo": dt,
        "inboundDepartureDateFrom": df, "inboundDepartureDateTo": dt,
        "durationFrom": CONFIG["nights_from"], "durationTo": CONFIG["nights_to"],
        "priceValueTo": CONFIG["max_price_pln"], "currency": "PLN",
        "limit": RYANAIR_LIMIT, "offset": offset,
    }
    url = RYANAIR_API + "?" + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def ryanair_fares():
    df, dt = daterange()
    raw, offset = [], 0
    try:
        while True:
            data = _ry_page(df, dt, offset)
            fares = data.get("fares", [])
            raw.extend(fares)
            total = data.get("size", len(raw))
            if len(fares) < RYANAIR_LIMIT or len(raw) >= total or offset > 400:
                break
            offset += RYANAIR_LIMIT
    except Exception as e:
        print(f"[blad] Ryanair: {e}", file=sys.stderr)
        return []

    out = []
    for f in raw:
        ob, ib = f.get("outbound", {}), f.get("inbound", {})
        arr = ob.get("arrivalAirport", {})
        price = f.get("summary", {}).get("price", {}).get("value")
        if price is None:
            continue
        out.append({
            "source": "Ryanair",
            "city": (arr.get("city", {}) or {}).get("name", arr.get("name", "?")),
            "country": arr.get("countryName", ""),
            "iata": arr.get("iataCode", "?"),
            "price": round(float(price), 2),
            "out_date": (ob.get("departureDate") or "")[:16],
            "in_date": (ib.get("departureDate") or "")[:16],
            "lat": None, "lon": None,
        })
    return out


# ─────────────────────────── WIZZ AIR ───────────────────────────
def wizz_version(proxies):
    """Wyciaga aktualna wersje API z homepage (zmienia sie co tydzien)."""
    import re
    for px in random.sample(proxies, min(5, len(proxies))):
        try:
            req = urllib.request.Request("https://wizzair.com/", headers={"User-Agent": UA})
            html = opener_for(px).open(req, timeout=25).read().decode("utf-8", "ignore")
            vers = re.findall(r"be\.wizzair\.com/([0-9.]+)/", html)
            if vers:
                return vers[0]
        except Exception:
            continue
    return None


def wizz_post(path, body, ver, proxies, tries=5):
    """POST do API Wizz z rotacja proxy."""
    data = json.dumps(body).encode() if body is not None else None
    method = "POST" if body is not None else "GET"
    url = f"https://be.wizzair.com/{ver}/Api/{path}"
    for px in random.sample(proxies, min(tries, len(proxies))):
        try:
            req = urllib.request.Request(
                url, data=data, method=method,
                headers={"User-Agent": UA, "Accept": "application/json",
                         "Content-Type": "application/json"})
            return json.loads(opener_for(px).open(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 404:      # zla wersja API — sygnal do gory
                raise
            continue
        except Exception:
            continue
    return None


def wizz_routes_from_origin(ver, proxies):
    """Mapa polaczen z origin + wspolrzedne miast."""
    m = wizz_post(f"asset/map?languageCode=en-GB", None, ver, proxies)
    if not m:
        return [], {}
    coords, conns = {}, []
    cities = m.get("cities", [])
    for c in cities:
        coords[c.get("iata")] = (c.get("latitude"), c.get("longitude"),
                                 c.get("shortName") or c.get("iata"),
                                 c.get("countryName", ""))
    for c in cities:
        if c.get("iata") == CONFIG["origin"]:
            conns = [x.get("iata") for x in c.get("connections", []) if x.get("iata")]
    return conns, coords


def _wizz_chunks():
    """Wizz timetable max ~30 dni na zapytanie — tnij okno na kawalki."""
    df, dt = daterange()
    start, end = date.fromisoformat(df), date.fromisoformat(dt)
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=28), end)
        yield cur.isoformat(), nxt.isoformat()
        cur = nxt + timedelta(days=1)


def wizz_route_deals(iata, ver, proxies, coords):
    """Najtanszy round-trip KTW<->iata w oknie dat i nocy (skanuje po ~28 dni)."""
    def cheap(flights, acc):
        for f in flights:
            amt = (f.get("price") or {}).get("amount")
            day = (f.get("departureDate") or "")[:10]
            if not amt or amt <= 0 or not day:
                continue
            if day not in acc or amt < acc[day]:
                acc[day] = amt

    outb, retb = {}, {}
    for cf, ct in _wizz_chunks():
        body = {"flightList": [
            {"departureStation": CONFIG["origin"], "arrivalStation": iata, "from": cf, "to": ct},
            {"departureStation": iata, "arrivalStation": CONFIG["origin"], "from": cf, "to": ct}],
            "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
        d = wizz_post("search/timetable", body, ver, proxies)
        if not d:
            continue
        cheap(d.get("outboundFlights", []), outb)
        cheap(d.get("returnFlights", []), retb)
    if not outb or not retb:
        return None

    best = None
    for od, op in outb.items():
        o = date.fromisoformat(od)
        for n in range(CONFIG["nights_from"], CONFIG["nights_to"] + 1):
            rd = (o + timedelta(days=n)).isoformat()
            if rd in retb:
                total = op + retb[rd]
                if best is None or total < best[0]:
                    best = (total, od, rd)
    if best is None or best[0] > CONFIG["max_price_pln"]:
        return None

    lat, lon, cname, country = coords.get(iata, (None, None, iata, ""))
    return {
        "source": "Wizz",
        "city": " ".join((cname or iata).split()),
        "country": " ".join(country.split()),
        "iata": iata,
        "price": round(best[0], 2),
        "out_date": best[1], "in_date": best[2],
        "lat": lat, "lon": lon,
    }


def wizz_fares():
    if not CONFIG["enable_wizz"]:
        return []
    proxies = load_proxies()
    if not proxies:
        print("[uwaga] brak proxy — pomijam Wizz (CONFIG['proxy_file'])", file=sys.stderr)
        return []
    ver = wizz_version(proxies)
    if not ver:
        print("[blad] Wizz: nie udalo sie wykryc wersji API przez proxy", file=sys.stderr)
        return []
    print(f"[wizz] wersja API {ver}", file=sys.stderr)
    conns, coords = wizz_routes_from_origin(ver, proxies)
    WIZZ_COORDS.update(coords)
    if not conns:
        print("[blad] Wizz: brak tras z origin (mapa pusta?)", file=sys.stderr)
        return []
    out = []
    for i, iata in enumerate(conns[:CONFIG["wizz_max_routes"]]):
        try:
            d = wizz_route_deals(iata, ver, proxies, coords)
        except urllib.error.HTTPError:
            # wersja sie zmienila w trakcie — wykryj ponownie raz
            ver2 = wizz_version(proxies)
            if ver2 and ver2 != ver:
                ver = ver2
                try:
                    d = wizz_route_deals(iata, ver, proxies, coords)
                except Exception:
                    d = None
            else:
                d = None
        if d:
            out.append(d)
        time.sleep(0.3)
    return out


# ─────────────────────────── MERGE / DEDUP / WYJSCIE ───────────────────────────
def deal_key(d):
    return f"{d['source']}|{d['iata']}|{d['out_date']}|{d['in_date']}|{d['price']}"


def load_seen():
    try:
        return set(json.load(open(CONFIG["seen_file"], encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen):
    json.dump(sorted(seen), open(CONFIG["seen_file"], "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)


def write_deals_json(deals):
    payload = {
        "generated": date.today().isoformat(),
        "origin": CONFIG["origin"],
        "pax": CONFIG["pax"],
        "max_price_pln": CONFIG["max_price_pln"],
        "deals": [dict(d, booking=booking_link(d), total=round(d["price"] * CONFIG["pax"], 2))
                  for d in deals],
    }
    json.dump(payload, open(CONFIG["deals_out"], "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def post_discord(deals):
    wh = CONFIG["discord_webhook"]
    if not wh:
        print("[uwaga] brak DISCORD_WEBHOOK — drukuje na ekran", file=sys.stderr)
        for d in deals:
            t = round(d["price"] * CONFIG["pax"], 2)
            print(f"{d['price']:>6.0f} zł/os ({t:.0f} zł/{CONFIG['pax']}os) "
                  f"[{d['source']}] {d['city']} {d['country']} [{d['iata']}] "
                  f"{d['out_date']} -> {d['in_date']}")
        return
    color = {"Ryanair": 0x0050a0, "Wizz": 0xc6007e}
    for i in range(0, len(deals), 10):
        embeds = []
        for d in deals[i:i + 10]:
            total = round(d["price"] * CONFIG["pax"], 2)
            embeds.append({
                "title": f"✈️ {d['city']} {d['country']} — {d['price']:.0f} zł/os",
                "color": color.get(d["source"], 0x1abc9c),
                "fields": [
                    {"name": "Tam", "value": d["out_date"].replace("T", " "), "inline": True},
                    {"name": "Powrót", "value": d["in_date"].replace("T", " "), "inline": True},
                    {"name": f"Razem ({CONFIG['pax']} os.)", "value": f"{total:.0f} zł", "inline": True},
                    {"name": "Hotel", "value": f"[Booking 🏨]({booking_link(d)})", "inline": True},
                ],
                "footer": {"text": f"{CONFIG['origin']} → {d['iata']} · {d['source']}"},
            })
        payload = {"content": "🔥 Nowe okazje lotnicze!" if i == 0 else None, "embeds": embeds}
        req = urllib.request.Request(wh, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": UA})
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            print(f"[blad] Discord {e.code}: {e.read().decode('utf-8','ignore')}", file=sys.stderr)
        except Exception as e:
            print(f"[blad] Discord: {e}", file=sys.stderr)
        time.sleep(0.5)


def main():
    ry = ryanair_fares()
    wz = wizz_fares()
    # Backfill wspolrzednych lotow Ryanair z mapy Wizz (po IATA) — na mapke.
    for d in ry:
        if d["lat"] is None and d["iata"] in WIZZ_COORDS:
            lat, lon, _c, _co = WIZZ_COORDS[d["iata"]]
            d["lat"], d["lon"] = lat, lon
    deals = ry + wz
    if CONFIG["only_countries"]:
        oc = [c.lower() for c in CONFIG["only_countries"]]
        deals = [d for d in deals if d["country"].lower() in oc or d["country"] == ""]
    deals.sort(key=lambda x: x["price"])

    if not deals:
        print("Brak ofert w kryteriach.")
        return

    write_deals_json(deals)   # strona zawsze ma aktualny pelny stan
    print(f"Znaleziono {len(deals)} ofert (zapisano deals.json)")

    seen = load_seen()
    fresh = [d for d in deals if deal_key(d) not in seen]
    print(f"Nowych (do Discord): {len(fresh)}")
    if not fresh:
        return
    post_discord(fresh)
    for d in fresh:
        seen.add(deal_key(d))
    save_seen(seen)
    print("Wyslano na Discord i zapisano dedup.")


if __name__ == "__main__":
    main()
