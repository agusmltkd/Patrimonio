#!/usr/bin/env python3
"""Envía las notificaciones push de Patrimonio.

La configuración llega en el secreto PUSH_CONFIG: uno o varios códigos
"PATRI1.<base64>" (uno por dispositivo, separados por espacios o saltos de
línea) que genera la propia app en Ajustes → Notificaciones. Cada código lleva
la clave privada VAPID creada en el iPhone, la suscripción y las preferencias.

El estado (qué se ha avisado ya) se guarda en notify-state.json para no
repetir avisos. La primera vez solo se inicializa, sin enviar nada.
"""
import base64
import calendar
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "notify-state.json"
NAVS_FILE = ROOT / "navs.json"
IPC_FILE = ROOT / "ipc.json"
APP_URL = "https://agusmltkd.github.io/Patrimonio/"
CONTACT = "mailto:agusmltkd@users.noreply.github.com"
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def load_json(p, default):
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return default


def parse_configs(raw):
    out = []
    for tok in (raw or "").split():
        if not tok.startswith("PATRI1."):
            continue
        b = tok[len("PATRI1."):]
        b += "=" * (-len(b) % 4)
        try:
            cfg = json.loads(base64.urlsafe_b64decode(b).decode("utf-8"))
            if cfg.get("k") and cfg.get("s", {}).get("endpoint"):
                out.append(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"Código no válido: {e}", file=sys.stderr)
    return out


def fmt_pct(x):
    return f"{x:.1f}".replace(".", ",") + " %"


def drawdown(hist, today_iso):
    if len(hist) < 20:
        return None
    one_year = (date.fromisoformat(hist[-1][0]) - timedelta(days=365)).isoformat()
    win = [r for r in hist if r[0] >= one_year]
    peak = max(win, key=lambda r: r[1])
    last = win[-1]
    return {"dd": (last[1] / peak[1] - 1) * 100, "peak": peak, "last": last,
            "ath": last[1] >= max(r[1] for r in hist)}


def events_for(cfg, state, today, init):
    """Devuelve la lista de avisos (title, body, url, tag) y actualiza 'state' (por dispositivo)."""
    ev = set(cfg.get("e", []))
    out = []
    ym = today.strftime("%Y-%m")
    name = cfg.get("n") or ""

    # Día de cobro
    payday = int(cfg.get("p") or 28)
    dim = calendar.monthrange(today.year, today.month)[1]
    if today.day >= min(payday, dim) and state.get("payday_month") != ym:
        if not init and "payday" in ev:
            out.append(("🗓️ Toca la revisión del mes",
                        f"{name + ', y' if name else 'Y'}a has cobrado: actualiza tus saldos y descarga el extracto del BBVA para ver en qué has gastado.",
                        APP_URL + "?tab=cuentas", "payday"))
        state["payday_month"] = ym

    # Mercado
    navs = load_json(NAVS_FILE, {}).get("funds", {})
    for isin in cfg.get("f") or []:
        f = navs.get(isin)
        if not f:
            continue
        d = drawdown(f.get("history", []), today.isoformat())
        if not d:
            continue
        fs = state.setdefault("funds", {}).setdefault(isin, {})
        level = 20 if d["dd"] <= -20 else 10 if d["dd"] <= -10 else 5 if d["dd"] <= -5 else 0
        prev = fs.get("drop_level", 0)
        if level > prev:
            if not init and "drop" in ev:
                dd = -d["dd"]
                msg = {5: "Es una bajada pequeña y muy habitual. No hace falta hacer nada.",
                       10: "Es una corrección: pasa cada uno o dos años. Lo habitual es seguir aportando igual.",
                       20: "Es un mercado bajista. Ha pasado otras veces y siempre se ha recuperado, aunque a veces tarda años. No vendas por miedo."}[level]
                out.append((f"{'🐻' if level == 20 else '🌧️' if level == 10 else '🌤️'} Tu fondo ha caído un {fmt_pct(dd)}",
                            f"Desde su máximo del {d['peak'][0][8:10]}/{d['peak'][0][5:7]}. {msg}",
                            APP_URL + "?tab=resumen", f"drop-{isin}"))
            fs["drop_level"] = level
        elif d["dd"] > -2.5 and prev:
            fs["drop_level"] = 0
        if d["ath"]:
            last_ath = fs.get("ath_date")
            if not last_ath or (today - date.fromisoformat(last_ath)).days >= 7:
                if not init and "ath" in ev and last_ath:
                    out.append(("🎉 Tu fondo está en máximos",
                                f"{f.get('name', isin)} ha marcado un nuevo máximo: {str(d['last'][1]).replace('.', ',')} € por participación.",
                                APP_URL + "?tab=cuentas", f"ath-{isin}"))
                fs["ath_date"] = today.isoformat()

    # IPC
    yoy = load_json(IPC_FILE, {}).get("yoy") or []
    if yoy:
        m, v = yoy[-1]
        if state.get("ipc_month") != m:
            if not init and "ipc" in ev and state.get("ipc_month"):
                mm = MONTHS[int(m[5:7]) - 1]
                out.append((f"🎈 Inflación de {mm}: {fmt_pct(v)}",
                            "El INE ha publicado el IPC. Mira cuánto le afecta a tu dinero.",
                            APP_URL + "?tab=resumen", "ipc"))
            state["ipc_month"] = m

    # Renta
    for (mon, day, key, title, body) in [
        (1, 20, "cert", "🧾 Certificados fiscales",
         "Ya puedes descargar los certificados de intereses y fondos de tus bancos. Apunta los intereses reales en la app (Resumen → Renta)."),
        (4, 8, "borrador", "🧾 Campaña de la renta",
         "Ya está disponible el borrador. Revísalo con la pantalla de Renta de la app antes de confirmarlo."),
    ]:
        k = f"{today.year}-{key}"
        if (today.month, today.day) >= (mon, day) and today.month <= mon + 1 and k not in state.setdefault("renta", []):
            if not init and "renta" in ev:
                out.append((title, body, APP_URL + "?tab=resumen", f"renta-{key}"))
            state["renta"].append(k)
    return out


def send(cfg, title, body, url, tag):
    from pywebpush import webpush, WebPushException
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False)
    try:
        webpush(subscription_info=cfg["s"], data=payload, vapid_private_key=cfg["k"],
                vapid_claims={"sub": CONTACT}, ttl=86400)
        print(f"Enviada: {title}")
        return True
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        print(f"Fallo al enviar ({code}): {e}", file=sys.stderr)
        if code in (404, 410):
            print("La suscripción ha caducado: vuelve a activar las notificaciones en la app y actualiza PUSH_CONFIG.", file=sys.stderr)
        return False


def main():
    configs = parse_configs(os.environ.get("PUSH_CONFIG"))
    if not configs:
        print("Sin PUSH_CONFIG: no hay notificaciones que enviar.")
        return
    test = os.environ.get("PUSH_TEST", "").lower() in ("1", "true", "yes")
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    all_state = load_json(STATE_FILE, {})
    for cfg in configs:
        dev = cfg["s"]["endpoint"][-16:]
        st = all_state.setdefault(dev, {})
        init = not st.get("initialized")
        if test:
            send(cfg, "🔔 Notificaciones activadas",
                 "Todo listo. Te avisaré del día de cobro, de las caídas del mercado y de lo demás que hayas elegido.",
                 APP_URL, "test")
        for title, body, url, tag in events_for(cfg, st, today, init):
            send(cfg, title, body, url, tag)
        st["initialized"] = True
    STATE_FILE.write_text(json.dumps(all_state, ensure_ascii=False, indent=1) + "\n", "utf-8")


if __name__ == "__main__":
    main()
