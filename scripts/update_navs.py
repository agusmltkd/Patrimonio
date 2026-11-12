#!/usr/bin/env python3
"""Actualiza navs.json con el valor liquidativo diario de los fondos de funds.json.

Fuentes, por orden:
  1. Financial Times: último precio y, la primera vez, varios años de histórico.
  2. Morningstar, por si FT falla.

Si una fuente falla se prueba la siguiente; si todas fallan para un fondo,
se conserva lo que ya había. Solo usa la biblioteca estándar de Python.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDS_FILE = ROOT / "funds.json"
NAVS_FILE = ROOT / "navs.json"
KEEP_YEARS = 5
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------- Morningstar ----------
def morningstar_id(isin):
    url = ("https://www.morningstar.es/es/util/SecuritySearch.ashx?source=nav&moduleId=6"
           "&ifIncludeAds=False&usrtType=v&q=" + urllib.parse.quote(isin))
    txt = get(url)
    m = re.search(r'"i"\s*:\s*"([A-Z0-9]{10})"', txt)
    if not m:
        raise ValueError("Morningstar no encontró el ISIN")
    name = txt.split("|", 1)[0].strip() or None
    return m.group(1), name


def morningstar_history(isin, currency, start):
    ms_id, name = morningstar_id(isin)
    url = ("https://tools.morningstar.es/api/rest.svc/timeseries_price/2nhcdckzon"
           f"?id={ms_id}%5D2%5D0%5DFOESP%24%24ALL&currencyId={currency}&idtype=Morningstar"
           f"&frequency=daily&startDate={start.isoformat()}&outputType=COMPACTJSON")
    data = json.loads(get(url))
    hist = []
    for ts, value in data:
        if value is None:
            continue
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
        hist.append([d, round(float(value), 6)])
    if not hist:
        raise ValueError("Morningstar devolvió una serie vacía")
    return hist, name


# ---------- Financial Times ----------
def ft_history(xid, start, end):
    rows = []
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=364))
        url = ("https://markets.ft.com/data/equities/ajax/get-historical-prices"
               f"?startDate={s:%Y/%m/%d}&endDate={e:%Y/%m/%d}&symbol={xid}")
        body = json.loads(get(url)).get("html", "")
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 5:
                continue
            dm = re.search(r"[A-Z][a-z]+day, ([A-Z][a-z]+) (\d{1,2}), (\d{4})", tds[0])
            if not dm:
                continue
            d = datetime.strptime(" ".join(dm.groups()), "%B %d %Y").date().isoformat()
            close = re.sub(r"<[^>]+>", "", tds[4]).replace(",", "").strip()
            try:
                rows.append([d, round(float(close), 6)])
            except ValueError:
                pass
        s = e + timedelta(days=1)
    return rows


def ft_source(isin, currency, start):
    txt = get(f"https://markets.ft.com/data/funds/tearsheet/summary?s={isin}:{currency}")
    m = re.search(r'mod-ui-data-list__value">\s*([\d.,]+)\s*<', txt)
    if not m:
        raise ValueError("FT: no se encontró el precio")
    price = float(m.group(1).replace(",", ""))
    dm = re.search(r"[Aa]s of ([A-Z][a-z]{2}) (\d{1,2}) (\d{4})", txt)
    d = datetime.strptime(" ".join(dm.groups()), "%b %d %Y").date().isoformat() if dm else date.today().isoformat()
    nm = re.search(r'mod-tearsheet-overview__header__name[^>]*>([^<]+)<', txt)
    hist = []
    xm = re.search(r'xid(?:&quot;|")\s*:\s*(?:&quot;|")(\d+)', txt)
    if xm:
        try:
            hist = ft_history(xm.group(1), start, date.today())
        except Exception as e:  # noqa: BLE001
            print(f"{isin}: sin histórico de FT ({e}); solo último precio", file=sys.stderr)
    hist.append([d, round(price, 6)])
    return hist, (html.unescape(nm.group(1).strip()) if nm else None)


def merge(old, new):
    by_date = {d: v for d, v in old}
    for d, v in new:
        by_date[d] = v
    cutoff = (date.today() - timedelta(days=365 * KEEP_YEARS)).isoformat()
    return [[d, by_date[d]] for d in sorted(by_date) if d >= cutoff]


def main():
    funds = json.loads(FUNDS_FILE.read_text("utf-8"))
    navs = json.loads(NAVS_FILE.read_text("utf-8")) if NAVS_FILE.exists() else {"funds": {}}
    navs.setdefault("funds", {})
    before = json.dumps(navs["funds"], sort_keys=True)
    ok = 0
    for f in funds:
        isin, cur = f["isin"].strip().upper(), f.get("currency", "EUR")
        entry = navs["funds"].setdefault(isin, {"name": f.get("label"), "currency": cur, "history": []})
        old = entry.get("history", [])
        start = (date.fromisoformat(old[-1][0]) - timedelta(days=10)) if old else date.today() - timedelta(days=365 * KEEP_YEARS)
        if len(old) < 30:
            start = date.today() - timedelta(days=365 * KEEP_YEARS)
        for source, fn in (("ft", lambda: ft_source(isin, cur, start)),
                           ("morningstar", lambda: morningstar_history(isin, cur, start))):
            try:
                hist, name = fn()
                entry["history"] = merge(old, hist)
                entry["source"] = source
                if name:
                    entry["name"] = html.unescape(name)
                last = entry["history"][-1]
                print(f"{isin}: {last[1]} ({last[0]}) vía {source}, {len(hist)} precios recibidos")
                ok += 1
                break
            except Exception as e:  # noqa: BLE001
                print(f"{isin}: falla {source}: {e}", file=sys.stderr)
        else:
            print(f"{isin}: sin datos nuevos, se mantiene lo anterior", file=sys.stderr)

    if json.dumps(navs["funds"], sort_keys=True) == before and NAVS_FILE.exists():
        print("Sin precios nuevos; navs.json no cambia")
        sys.exit(0 if ok else 1)
    navs["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    NAVS_FILE.write_text(json.dumps(navs, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    if ok == 0:
        print("No se pudo actualizar ningún fondo", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
