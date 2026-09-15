#!/usr/bin/env python3
"""Recupera i prezzi giornalieri e scrive prezzi.json (usato dalla pagina BIPER)."""
import json, re, sys, time, urllib.request, urllib.error, datetime, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "prezzi.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "it-IT,it;q=0.9"}

# id pagina -> sorgente. yahoo: prezzo per unità (BTP in %, fondi = NAV). bi: pagina Borsa Italiana.
ITEMS = {
    "t2":  {"src": "yahoo", "sym": "IT0001086567.MI"},
    "t3":  {"src": "yahoo", "sym": "IT0005583486.MI"},
    "t4":  {"src": "yahoo", "sym": "IT0005547408.MI"},
    "t8":  {"src": "bi",    "url": "https://www.borsaitaliana.it/borsa/cw-e-certificates/eurotlx/scheda/IT0005709875.html"},
    "t10": {"src": "yahoo", "sym": "0P0002EMIO.F"},
}

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def get_retry(urls, tries=3):
    last = None
    for i in range(tries):
        for u in urls:
            try:
                return get(u)
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503):
                    raise
            except Exception as e:
                last = e
        time.sleep(5 * (i + 1))
    raise last

def yahoo(sym):
    q = f"/v8/finance/chart/{sym}?interval=1d&range=10d"
    d = json.loads(get_retry([f"https://query1.finance.yahoo.com{q}", f"https://query2.finance.yahoo.com{q}"]))
    time.sleep(1.5)
    res = d["chart"]["result"][0]
    m = res["meta"]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = m.get("regularMarketPrice") or (closes[-1] if closes else None)
    prev = m.get("chartPreviousClose")
    if (prev is None or prev == price) and len(closes) >= 2:
        prev = closes[-2]
    ts = m.get("regularMarketTime")
    date = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if ts else None
    return {"price": round(float(price), 4), "prev": round(float(prev), 4) if prev else None, "date": date, "src": "yahoo"}

def num_it(s):
    return float(s.replace(".", "").replace(",", "."))

def borsa_italiana(url, old):
    h = get(url)
    def field(label):
        m = re.search(re.escape(label) + r"</strong>\s*</span>\s*</td>\s*<td>\s*<span[^>]*>\s*([0-9.,]*)\s*<", h)
        return num_it(m.group(1)) if m and m.group(1) else None
    ultimo = field("Prezzo ultimo contratto")
    rif = field("Prezzo di riferimento")
    price = ultimo or rif
    if price is None:
        raise RuntimeError("prezzo non trovato nella pagina")
    # prev: riferimento se c'è un contratto oggi, altrimenti il prezzo del giorno precedente salvato
    if ultimo and rif and rif != ultimo:
        prev = rif
    elif old and old.get("price") not in (None, price):
        prev = old["price"]
    else:
        prev = (old or {}).get("prev")
    return {"price": price, "prev": prev, "date": datetime.date.today().isoformat(), "src": "borsaitaliana"}

def main():
    old = {}
    if OUT.exists():
        try: old = json.loads(OUT.read_text()).get("items", {})
        except Exception: pass
    items, errors = {}, {}
    for tid, cfg in ITEMS.items():
        try:
            items[tid] = yahoo(cfg["sym"]) if cfg["src"] == "yahoo" else borsa_italiana(cfg["url"], old.get(tid))
            print(f"OK  {tid}: {items[tid]}")
        except Exception as e:
            errors[tid] = str(e)[:120]
            if tid in old: items[tid] = old[tid]   # mantieni l'ultimo valore noto
            print(f"ERR {tid}: {e}", file=sys.stderr)
    out = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "items": items, "errors": errors}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("scritto", OUT)
    return 0 if items else 1

if __name__ == "__main__":
    sys.exit(main())
