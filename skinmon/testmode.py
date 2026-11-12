"""Modo de teste: teto temporário para provocar um alerta com oferta real, com o assunto marcado como [TESTE].

O teto original de cada alerta ativo fica guardado no banco e volta ao encerrar o teste, mesmo que o
monitor seja reiniciado no meio."""
from __future__ import annotations

import json

KEY = "teste"


def state(db) -> dict:
    try:
        data = json.loads(db.get(KEY) or "{}")
    except ValueError:
        data = {}
    return {"active": bool(data.get("original")), "ceiling": data.get("ceiling"), "original": data.get("original") or {}}


def start(db, ceiling: float) -> dict:
    current = state(db)
    original = dict(current["original"])
    for alert in db.alerts(active_only=True):
        original.setdefault(str(alert.id), alert.max_price)  # um segundo início não perde o teto original
        db.update_alert(alert.id, max_price=float(ceiling))
    db.set(KEY, json.dumps({"ceiling": float(ceiling), "original": original}))
    db.set("assunto_teste", "1")
    return original


def finish(db) -> dict:
    """Restaura os tetos guardados. Devolve {alert_id: teto restaurado}."""
    restored = {}
    for alert_id, price in state(db)["original"].items():
        if db.get_alert(int(alert_id)) is not None:
            db.update_alert(int(alert_id), max_price=float(price))
            restored[int(alert_id)] = float(price)
    db.set(KEY, "{}")
    db.set("assunto_teste", "0")
    return restored
