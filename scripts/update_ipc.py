#!/usr/bin/env python3
"""Descarga el IPC general de España (INE) y lo guarda en ipc.json.

Usa la API JSON oficial del INE (servicios.ine.es/wstempus). Se descarga el
índice general nacional y, si no está, la variación anual. Con el índice se
calcula todo lo demás (variación anual, inflación acumulada entre dos fechas).
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ipc.json"
API = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/{code}?nult={n}"
# Índice general nacional y su variación anual (base 2021)
INDEX_CODES = ["IPC251852"]
YOY_CODES = ["IPC251856"]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Patrimonio-PWA/1.0 (+github.com/agusmltkd/Patrimonio)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def series(code, n=200):
    d = get_json(API.format(code=code, n=n))
    if isinstance(d, list):
        d = d[0] if d else {}
    name = d.get("Nombre", "")
    rows = []
    for p in d.get("Data", []):
        v = p.get("Valor")
        if v is None:
            continue
        year = p.get("Anyo")
        month = p.get("FK_Periodo")
        if not year or not month or not (1 <= int(month) <= 12):
            fecha = p.get("Fecha")
            if fecha is None:
                continue
            dt = datetime.fromtimestamp(fecha / 1000, tz=timezone.utc)
            year, month = dt.year, dt.month
        rows.append([f"{int(year)}-{int(month):02d}", round(float(v), 4)])
    rows.sort()
    return name, rows


def main():
    out = {"source": "INE · IPC general nacional"}
    for code in INDEX_CODES:
        try:
            name, rows = series(code)
            print(f"{code}: {name} · {len(rows)} meses · último {rows[-1] if rows else '-'}")
            if rows and "índice" in name.lower() and "variación" not in name.lower():
                out["index"] = rows
                out["index_name"] = name
                break
            print(f"{code}: no parece el índice general, se ignora", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"{code}: falla: {e}", file=sys.stderr)
    for code in YOY_CODES:
        try:
            name, rows = series(code)
            print(f"{code}: {name} · {len(rows)} meses · último {rows[-1] if rows else '-'}")
            if rows and "anual" in name.lower():
                out["yoy"] = rows
                out["yoy_name"] = name
                break
        except Exception as e:  # noqa: BLE001
            print(f"{code}: falla: {e}", file=sys.stderr)

    if "yoy" not in out and "index" in out:
        idx = dict(out["index"])
        yoy = []
        for m, v in out["index"]:
            y, mm = m.split("-")
            prev = idx.get(f"{int(y) - 1}-{mm}")
            if prev:
                yoy.append([m, round((v / prev - 1) * 100, 2)])
        out["yoy"] = yoy

    if "index" not in out and "yoy" not in out:
        print("No se pudo descargar el IPC", file=sys.stderr)
        sys.exit(0 if OUT.exists() else 1)

    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    if old.get("index") == out.get("index") and old.get("yoy") == out.get("yoy"):
        print("IPC sin cambios")
        return
    out["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")


if __name__ == "__main__":
    main()
