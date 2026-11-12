"""Agendador: cada loja roda em sua própria thread, no seu intervalo. Falha de uma não afeta as outras."""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import net
from .engine import Engine
from .mailer import brasilia_time, format_brl, render_notice
from .pricing import CostSettings, MarketFees
from .sources.base import Ctx, PollResult

MAX_BACKOFF = 900  # espera máxima entre tentativas de uma loja com falha
RATE_LIMIT_WAIT = 600  # espera mínima quando a loja responde "muitas requisições"
DOWN_WARNING_AFTER = 3600  # avisa por e-mail quando a loja falha por este tempo seguido
DUE_SLACK = 90  # segundos de folga ao decidir se a vez de uma loja já chegou


@dataclass(frozen=True)
class Outcome:
    state: str  # ok | erro | limite | desativada | sem alertas
    wait: float  # segundos até a próxima consulta


class Runner:
    def __init__(self, db, send, sources, fx_rates, now=time.time, log=print, max_per_hour=30):
        self.db, self.send, self.sources, self.fx_rates, self.now, self.log = db, send, list(sources), fx_rates, now, log
        self.engine = Engine(db, send, now=now, max_per_hour=max_per_hour)

    # ---- configuração efetiva de cada loja ---------------------------------
    def market_config(self, source) -> dict:
        row = self.db.market_overrides().get(source.id)
        if row is None:
            return {"enabled": source.default_enabled, "fee_pct": source.default_fee_pct, "fee_fixed": source.default_fee_fixed,
                    "spread_pct": source.default_spread_pct, "iof_pct": source.default_iof_pct}
        return {"enabled": bool(row["enabled"]), "fee_pct": row["fee_pct"], "fee_fixed": row["fee_fixed"],
                "spread_pct": row["spread_pct"], "iof_pct": row["iof_pct"]}

    def cost_settings(self) -> CostSettings:
        return CostSettings(iof_pct=self.db.get_float("iof_pct", 3.5), spread_pct=self.db.get_float("spread_pct", 4.0))

    # ---- uma consulta ---------------------------------------------------------
    def poll_once(self, source) -> Outcome:
        now = self.now()
        cfg = self.market_config(source)
        if not cfg["enabled"]:
            self.db.set_status(source.id, state="desativada", error="", note="")
            return Outcome("desativada", source.interval)
        alerts = self.db.alerts(active_only=True)
        if not alerts:
            self.db.set_status(source.id, state="sem alertas", error="", note="")
            return Outcome("sem alertas", source.interval)

        try:
            rates = self.fx_rates() or {}
        except Exception:
            rates = {}
        ctx = Ctx(fx=rates)
        started = time.monotonic()
        try:
            result = source.poll(alerts, ctx)
        except net.RateLimited as exc:
            result = PollResult(errors=[str(exc)], rate_limited=exc.retry_after or RATE_LIMIT_WAIT)
        except Exception as exc:
            result = PollResult(errors=[str(exc) or exc.__class__.__name__])
        duration = int((time.monotonic() - started) * 1000)

        fees = MarketFees(pay_kind=source.pay_kind, fee_pct=cfg["fee_pct"], fee_fixed=cfg["fee_fixed"] or 0.0,
                          spread_pct=cfg.get("spread_pct"), iof_pct=cfg.get("iof_pct"))
        settings, info = self.cost_settings(), source.info()
        matched = eligible = emails = 0
        best_brl, best_name, mail_errors = None, None, []
        for alert in alerts:
            if alert.id not in result.offers:
                continue
            try:
                res = self.engine.process(info, alert, result.offers[alert.id], fees, settings, rates)
            except Exception as exc:
                mail_errors.append(f"{alert.name}: {exc}")
                continue
            matched += res.matched
            eligible += res.eligible
            emails += res.emails
            if res.error:
                mail_errors.append(res.error)
            if res.best_brl is not None and (best_brl is None or res.best_brl < best_brl):
                best_brl, best_name = res.best_brl, res.best_name

        notes = list(ctx.notes)
        if source.currency != "BRL" and not rates.get(source.currency):
            notes.append(f"câmbio indisponível: ofertas em {source.currency} não avaliadas")
        total_failure = bool(result.errors) and not result.offers
        prev = self.db.get_status(source.id)
        fields = {
            "last_poll": now, "duration_ms": duration, "matched": matched, "eligible": eligible,
            "best_brl": best_brl, "best_name": best_name, "note": "; ".join(notes)[:500],
            "error": "; ".join(list(result.errors) + mail_errors)[:500],
        }
        if total_failure:
            fails = int(prev.get("fails") or 0) + 1
            down_since = prev.get("down_since") or now
            fields.update(fails=fails, down_since=down_since, state="limite" if result.rate_limited else "erro")
            wait = min(source.interval * 2 ** min(fails, 10), MAX_BACKOFF)
            if not prev.get("down_notified") and now - down_since >= DOWN_WARNING_AFTER:
                fields["down_notified"] = self._warn_down(source, down_since, fields["error"])
        else:
            fields.update(last_ok=now, fails=0, down_since=None, down_notified=False, state="erro" if result.errors else "ok")
            wait = source.interval
        if emails:
            fields["last_email"] = now
        if result.rate_limited:
            outcome = Outcome("limite", max(wait, result.rate_limited, RATE_LIMIT_WAIT))
        else:
            outcome = Outcome(fields["state"], wait)
        # Próxima vez desta loja, para o modo rodada (cada execução é um processo novo). A folga absorve
        # o atraso da agenda do GitHub sem pular uma consulta inteira.
        fields["next_poll"] = now + outcome.wait - min(DUE_SLACK, outcome.wait / 4)
        self.db.set_status(source.id, **fields)
        return outcome

    def _warn_down(self, source, down_since, error) -> bool:
        if self.db.get("aviso_falha", "1") != "1":
            return True
        subject, text, html = render_notice(
            f"Monitor de skins: {source.label} sem resposta há mais de 1 hora",
            [
                f"A loja {source.label} falha desde {brasilia_time(down_since)} (horário de Brasília).",
                f"Último erro: {error or 'sem detalhe'}",
                "As outras lojas continuam sendo consultadas. Você recebe este aviso uma vez por queda.",
            ],
        )
        try:
            self.send(subject, text, html)
            return True
        except Exception:
            return False

    # ---- execução ---------------------------------------------------------
    def _safe_poll(self, source) -> Outcome:
        try:
            return self.poll_once(source)
        except Exception as exc:  # erro inesperado do próprio monitor: registra e segue
            self.log(f"{source.label}: erro interno: {exc!r}")
            return Outcome("erro", min(source.interval * 2, MAX_BACKOFF))

    def run_once(self) -> list:
        """Consulta todas as lojas uma vez, em paralelo. Devolve [(loja, resultado)] na ordem das lojas."""
        return self._run(self.sources)

    def run_due(self, force: bool = False) -> list:
        """Modo rodada: consulta só as lojas cuja vez chegou (ou todas, com force)."""
        now = self.now()
        due = [s for s in self.sources if force or now >= (self.db.get_status(s.id).get("next_poll") or 0)]
        return self._run(due)

    def _run(self, sources) -> list:
        if not sources:
            return []
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            outcomes = list(pool.map(self._safe_poll, sources))
        return list(zip(sources, outcomes))

    def describe(self, source) -> str:
        st = self.db.get_status(source.id)
        parts = [f"{source.label}: {st.get('state', 'aguardando')}"]
        if st.get("matched") is not None and st.get("state") in ("ok", "erro"):
            parts.append(f"{st['matched']} oferta(s) da skin")
        if st.get("best_brl") is not None:
            parts.append(f"menor {format_brl(st['best_brl'])}")
        if st.get("eligible"):
            parts.append(f"{st['eligible']} dentro do teto")
        if st.get("error"):
            parts.append("erro: " + st["error"])
        if st.get("note"):
            parts.append(st["note"])
        return " | ".join(parts)

    def _loop(self, source, stop: threading.Event):
        stop.wait(random.uniform(0, 3))  # evita todas as lojas no mesmo instante
        last_line = None
        while not stop.is_set():
            before = self.db.get_status(source.id).get("last_email")
            outcome = self._safe_poll(source)
            line = self.describe(source)
            sent = self.db.get_status(source.id).get("last_email") != before
            if line != last_line or sent:  # só registra mudança, para o log não crescer à toa
                self.log(line + (" | e-mail enviado" if sent else ""))
                last_line = line
            stop.wait(outcome.wait)

    def _housekeeping(self, stop: threading.Event):
        while not stop.is_set():
            try:
                self.db.prune(self.now())
            except Exception as exc:
                self.log(f"limpeza: {exc!r}")
            stop.wait(6 * 3600)

    def start(self, stop: threading.Event) -> list:
        threads = [threading.Thread(target=self._loop, args=(s, stop), name=s.id, daemon=True) for s in self.sources]
        threads.append(threading.Thread(target=self._housekeeping, args=(stop,), name="limpeza", daemon=True))
        for t in threads:
            t.start()
        return threads
