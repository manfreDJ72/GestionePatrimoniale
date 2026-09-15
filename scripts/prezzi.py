#!/usr/bin/env python3
"""Recupera i prezzi giornalieri e scrive prezzi.json (letto dalla pagina BIPER).
Fonte primaria: Borsa Italiana (raggiungibile dai runner GitHub). Riserva: Yahoo Finance."""
import json, re, sys, time, html, urllib.request, urllib.error, datetime, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "prezzi.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "it-IT,it;q=0.9"}
BI = "https://www.borsaitaliana.it/borsa"

# kind: btp = prezzo in % del nominale; fondo = NAV per quota; cert = prezzo per certificato (EUR)
ITEMS = {
    "t2":  {"kind": "btp",   "bi": f"{BI}/obbligazioni/mot/btp/scheda/IT0001086567.html", "yahoo": "IT0001086567.MI"},
    "t3":  {"kind": "btp",   "bi": f"{BI}/obbligazioni/mot/btp/scheda/IT0005583486.html", "yahoo": "IT0005583486.MI"},
    "t4":  {"kind": "btp",   "bi": f"{BI}/obbligazioni/mot/btp/scheda/IT0005547408.html", "yahoo": "IT0005547408.MI"},
    "t8":  {"kind": "cert",  "bi": f"{BI}/cw-e-certificates/eurotlx/scheda/IT0005709875.html"},
    "t10": {"kind": "fondo", "bi": f"{BI}/fondi/dettaglio/1FADB1181486.html?lang=it", "yahoo": "0P0002EMIO.F"},
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
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except Exception as e:
                last = e
        time.sleep(5 * (i + 1))
    raise last

def num_it(s):
    s = s.strip().replace("%", "").replace("+", "")
    return float(s.replace(".", "").replace(",", ".")) if s else None

def today():
    return datetime.date.today().isoformat()

def borsa_italiana(url, kind, old):
    h = get_retry([url])
    if "Pagina Non Trovata" in h:
        raise RuntimeError("pagina non trovata")
    def field(label):
        m = re.search(re.escape(label) + r"</strong>\s*</span>\s*</td>\s*<td[^>]*>\s*<span[^>]*>\s*([^<]*?)\s*<", h)
        return num_it(html.unescape(m.group(1))) if m and m.group(1).strip() else None
    m = re.search(r'-formatPrice"?[^>]*>\s*<strong>\s*([0-9.,]+)\s*</strong>', h)
    last = num_it(m.group(1)) if m else None
    m = re.search(r'-percPrice"?[^>]*>\s*<strong>\s*([+\-]?[0-9.,]+)%', h)
    var = num_it(m.group(1)) if m else None
    rif = field("Prezzo di riferimento")
    date = today()
    m = re.search(r'Data di riferimento</strong>\s*</span>\s*</td>\s*<td[^>]*>\s*<span[^>]*>\s*(\d\d/\d\d/\d{2,4})', h)
    if kind == "fondo":
        m = re.search(r'Data:\s*(?:<[^>]+>\s*)*(\d\d/\d\d/\d\d)', h)
    elif kind == "btp" and last:
        m = None   # prezzo live: la data è oggi
    if m:
        d, mo, y = m.group(1).split("/")
        y = y if len(y) == 4 else "20" + y
        date = f"{y}-{mo}-{d}"
    if kind == "cert":
        ultimo = field("Prezzo ultimo contratto")
        price = ultimo or rif
        if price is None: raise RuntimeError("prezzo non trovato")
        if ultimo and rif and rif != ultimo: prev = rif
        elif old and old.get("price") not in (None, price): prev = old["price"]
        else: prev = (old or {}).get("prev")
        return {"price": price, "prev": prev, "date": date, "src": "borsaitaliana"}
    price = last or rif
    if price is None: raise RuntimeError("prezzo non trovato")
    if var is not None and var != 0:
        prev = round(price / (1 + var / 100), 4)
    elif old and old.get("price") not in (None, price):
        prev = old["price"]
    else:
        prev = (old or {}).get("prev") or (rif if rif and rif != price else None)
    return {"price": price, "prev": prev, "date": date, "src": "borsaitaliana"}

def yahoo(sym):
    q = f"/v8/finance/chart/{sym}?interval=1d&range=10d"
    d = json.loads(get_retry([f"https://query1.finance.yahoo.com{q}", f"https://query2.finance.yahoo.com{q}"]))
    res = d["chart"]["result"][0]; m = res["meta"]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = m.get("regularMarketPrice") or (closes[-1] if closes else None)
    prev = m.get("chartPreviousClose")
    if (prev is None or prev == price) and len(closes) >= 2: prev = closes[-2]
    ts = m.get("regularMarketTime")
    date = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if ts else today()
    return {"price": round(float(price), 4), "prev": round(float(prev), 4) if prev else None, "date": date, "src": "yahoo"}

def main():
    old = {}
    if OUT.exists():
        try: old = json.loads(OUT.read_text()).get("items", {})
        except Exception: pass
    items, errors = {}, {}
    for tid, cfg in ITEMS.items():
        errs = []
        for src in ("bi", "yahoo"):
            if src not in cfg: continue
            try:
                items[tid] = borsa_italiana(cfg["bi"], cfg["kind"], old.get(tid)) if src == "bi" else yahoo(cfg["yahoo"])
                print(f"OK  {tid} [{src}]: {items[tid]}"); break
            except Exception as e:
                errs.append(f"{src}: {str(e)[:80]}"); time.sleep(1)
        if tid not in items:
            errors[tid] = " | ".join(errs)
            if tid in old: items[tid] = old[tid]   # mantieni l'ultimo valore noto
            print(f"ERR {tid}: {errors[tid]}", file=sys.stderr)
        time.sleep(1.5)
    out = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "items": items, "errors": errors}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("scritto", OUT)
    return 0 if items else 1

if __name__ == "__main__":
    sys.exit(main())
