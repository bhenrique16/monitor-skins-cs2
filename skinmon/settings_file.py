"""config.json: alertas, lojas e custos editáveis pelo GitHub (inclusive no celular).

No modo rodada (GitHub Actions) este arquivo é a fonte da verdade: a cada execução o banco é
sincronizado com ele, mantendo o histórico de cada alerta enquanto a skin continuar a mesma."""
from __future__ import annotations

import json
import os

from . import names
from .panel import parse_pct, parse_price

_BASIS = {"total": "total", "anunciado": "listed", "listed": "listed"}
_STATTRAK = {"qualquer": "any", "any": "any", "somente": "only", "so": "only", "only": "only", "sem": "exclude", "exclude": "exclude"}


def _bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "sim", "yes")


def _alert(raw, index):
    if not isinstance(raw, dict):
        raise ValueError(f"config.json: o alerta {index} precisa ser um objeto com skin e teto")
    skin = str(raw.get("skin") or "").strip()
    label = skin or f"número {index}"
    name = names.parse(skin).base
    if not name:
        raise ValueError(f"config.json: o alerta {index} está sem o nome da skin")
    teto = raw.get("teto")
    price = float(teto) if isinstance(teto, (int, float)) and not isinstance(teto, bool) else parse_price(teto)
    if not price or price <= 0:
        raise ValueError(f'config.json: teto inválido no alerta "{label}". Use reais, por exemplo 1700 ou "1.700,00"')
    basis = _BASIS.get(str(raw.get("comparar", "total")).strip().lower())
    if not basis:
        raise ValueError(f'config.json: "comparar" do alerta "{label}" deve ser "total" ou "anunciado"')
    stattrak = _STATTRAK.get(str(raw.get("stattrak", "qualquer")).strip().lower().replace("ó", "o"))
    if not stattrak:
        raise ValueError(f'config.json: "stattrak" do alerta "{label}" deve ser "qualquer", "somente" ou "sem"')
    wears = []
    for wear in raw.get("desgastes") or []:
        code = str(wear).strip().upper()
        if code not in names.WEAR_NAMES:
            raise ValueError(f'config.json: desgaste "{wear}" inválido no alerta "{label}". Use FN, MW, FT, WW ou BS')
        if code not in wears:
            wears.append(code)
    order = list(names.WEAR_NAMES)
    return {
        "name": name, "max_price": round(price, 2), "basis": basis, "stattrak": stattrak,
        "wears": tuple(sorted(wears, key=order.index)),
        "include_incomplete": _bool(raw.get("aceitar_total_incompleto"), True),
        "active": _bool(raw.get("ativo"), True),
    }


def _store(raw, store_id):
    if not isinstance(raw, dict):
        raise ValueError(f'config.json: a loja "{store_id}" precisa ser um objeto')
    out = {}
    if "ativa" in raw:
        out["enabled"] = _bool(raw["ativa"], True)
    if "taxa_percentual" in raw:
        value = raw["taxa_percentual"]
        out["fee_pct"] = None if value is None else parse_pct(value)
    if "taxa_fixa" in raw:
        out["fee_fixed"] = parse_pct(raw["taxa_fixa"]) or 0.0
    for key, field in (("spread", "spread_pct"), ("iof", "iof_pct")):
        if key in raw:
            out[field] = _signed(raw[key], f'config.json: "{key}" da loja "{store_id}" precisa ser um número em porcentagem ou null')
    return out


def _signed(value, message):
    """Percentual que pode ser negativo (câmbio da loja abaixo do comercial). None = usar o valor global."""
    if value is None:
        return None
    try:
        return float(str(value).strip().replace("%", "").replace(",", "."))
    except ValueError:
        raise ValueError(message) from None


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise ValueError(f"config.json não encontrado em {os.path.abspath(path)}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"config.json inválido na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}. "
                         "Confira vírgulas e aspas.") from None
    if not isinstance(data, dict):
        raise ValueError("config.json precisa ser um objeto com a lista \"alertas\"")
    alerts = [_alert(raw, i + 1) for i, raw in enumerate(data.get("alertas") or [])]
    stores = {str(k): _store(v, k) for k, v in (data.get("lojas") or {}).items() if not str(k).startswith("_")}
    costs = None
    if isinstance(data.get("custos"), dict):
        iof, spread = parse_pct(data["custos"].get("iof", 3.5)), parse_pct(data["custos"].get("spread", 4.0))
        if iof is None or spread is None:
            raise ValueError('config.json: "custos" precisa de "iof" e "spread" em porcentagem')
        costs = {"iof_pct": iof, "spread_pct": spread}
    return {"alertas": alerts, "lojas": stores, "custos": costs,
            "avisar_loja_fora_do_ar": _bool(data.get("avisar_loja_fora_do_ar"), True)}


def sync(db, cfg: dict, defaults=None) -> None:
    """Aplica o arquivo ao banco. defaults: {loja: {"enabled", "fee_pct", "fee_fixed"}} de cada loja."""
    defaults = defaults or {}
    existing = {names.key(a.name): a for a in db.alerts()}
    wanted = set()
    for alert in cfg["alertas"]:
        key = names.key(alert["name"])
        wanted.add(key)
        if key in existing:
            db.update_alert(existing[key].id, **alert)
        else:
            db.add_alert(**alert)
    for key, alert in existing.items():
        if key not in wanted:
            db.delete_alert(alert.id)

    for store_id in list(db.market_overrides()):
        if store_id not in cfg["lojas"]:
            db.delete_market(store_id)
    for store_id, values in cfg["lojas"].items():
        merged = {"enabled": True, "fee_pct": 0.0, "fee_fixed": 0.0, "spread_pct": None, "iof_pct": None}
        merged.update(defaults.get(store_id, {}))
        merged.update(values)
        db.set_market(store_id, merged["enabled"], merged["fee_pct"], merged["fee_fixed"],
                      spread_pct=merged["spread_pct"], iof_pct=merged["iof_pct"])

    if cfg["custos"]:
        db.set("iof_pct", cfg["custos"]["iof_pct"])
        db.set("spread_pct", cfg["custos"]["spread_pct"])
    db.set("aviso_falha", "1" if cfg["avisar_loja_fora_do_ar"] else "0")
