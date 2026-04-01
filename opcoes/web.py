from __future__ import annotations

import datetime
import math
import os
import re
import threading
import time
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Optional
from zoneinfo import ZoneInfo

from flask import Flask, g, redirect, render_template, request, session, url_for
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

from .auth import (
    authenticate_user,
    ensure_bootstrap_user_from_env,
    normalize_username,
)
from .config import (
    reset_pg_schema_override,
    set_pg_schema_override,
)
from .db import open_db
from .runtime_env import load_dotenv_once
from .portfolio import (
    add_position,
    delete_position,
    list_positions,
    summarize_realized_positions,
    update_position,
    close_position,
    get_position,
)
from .utils import infer_option_type, parse_ptbr_number
from .settings import (
    CashCoveredPutSettings,
    CoveredCallSettings,
    FeeSettings,
    StrategySettings,
    FundamentusSettings,
    get_cash_put_settings,
    get_covered_call_settings,
    get_fee_settings,
    get_strategy_settings,
    get_fundamentus_settings,
    update_cash_put_settings,
    update_covered_call_settings,
    update_fee_settings,
    update_strategy_settings,
    update_fundamentus_settings,
)
from .service_runs import get_service_dashboard
from .strategies import (
    get_cash_covered_put_context,
    get_covered_call_context,
    get_fundamentus_context,
    get_ranking_context,
)
from .flows import FlowError, assign_put, callaway
from . import finance, darf
from .tax import (
    build_position_tax_events,
    compute_tax,
    list_monthly_tax_summaries,
    list_tax_events_for_period,
)

DEFAULT_SECRET_KEY = "troque-esta-chave-em-producao"
CSRF_FIELD_NAME = "_csrf_token"
LOCAL_DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.getenv(name, "1" if default else "0").strip().lower()
        return raw in {"1", "true", "yes", "on", "sim", "s"}

    def _env_int(name: str, default: int, minimum: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            value = default
        return max(value, minimum)

    def _skip_production_checks() -> bool:
        return _env_bool("OPCOES_SKIP_PRODUCTION_CHECKS", False)

    def _is_debug_mode() -> bool:
        return _env_bool("OPCOES_WEB_DEBUG", False)

    secret_key = (os.getenv("OPCOES_SECRET_KEY") or "").strip() or DEFAULT_SECRET_KEY
    if not _is_debug_mode() and not _skip_production_checks():
        if secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "Defina OPCOES_SECRET_KEY com um valor forte e unico antes de iniciar a aplicacao em producao."
            )
    app.secret_key = secret_key
    ensure_bootstrap_user_from_env()
    ranking_cache: dict[tuple, tuple[float, dict]] = {}
    ranking_cache_lock = threading.Lock()
    login_attempts: dict[str, dict[str, float | int]] = {}
    login_attempts_lock = threading.Lock()
    ranking_cache_write_endpoints = {
        "darf_generate",
        "darf_pay",
        "finance_add",
        "finance_assign",
        "finance_callaway",
        "finance_expire",
        "finance_update",
        "finance_delete",
        "settings_view",
        "add_position_view",
        "register_position_premium",
        "recalc_position_premium",
        "update_position_view",
        "delete_position_view",
    }

    def _session_idle_timeout_seconds() -> int:
        raw = os.getenv("OPCOES_SESSION_IDLE_MINUTES", "15").strip()
        try:
            minutes = int(raw)
        except ValueError:
            minutes = 15
        if minutes <= 0:
            minutes = 15
        return minutes * 60

    def _utc_now_ts() -> int:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    def _ranking_cache_ttl_seconds() -> int:
        raw = os.getenv("OPCOES_RANKING_CACHE_SECONDS", "45").strip()
        try:
            ttl = int(raw)
        except ValueError:
            ttl = 45
        return max(ttl, 0)

    def _ranking_cache_namespace(username: str | None) -> str:
        normalized = normalize_username(username or "")
        if normalized:
            return f"user:{normalized}"
        return "global"

    def _current_ranking_cache_namespace() -> str:
        username = getattr(g, "current_username", None)
        if not username:
            username = normalize_username(session.get("username") or "")
        return _ranking_cache_namespace(username)

    def _ranking_cache_key() -> tuple:
        args_signature = tuple(
            (key, tuple(sorted(str(v) for v in request.args.getlist(key))))
            for key in sorted(request.args.keys())
        )
        backend = "postgres"
        return ("index", backend, _current_ranking_cache_namespace(), args_signature)

    def _get_ranking_cache(cache_key: tuple) -> Optional[dict]:
        ttl = _ranking_cache_ttl_seconds()
        if ttl <= 0:
            return None
        now = time.monotonic()
        with ranking_cache_lock:
            entry = ranking_cache.get(cache_key)
            if not entry:
                return None
            expires_at, payload = entry
            if expires_at <= now:
                ranking_cache.pop(cache_key, None)
                return None
            return payload

    def _set_ranking_cache(cache_key: tuple, payload: dict) -> None:
        ttl = _ranking_cache_ttl_seconds()
        if ttl <= 0:
            return
        now = time.monotonic()
        expires_at = now + float(ttl)
        with ranking_cache_lock:
            ranking_cache[cache_key] = (expires_at, payload)
            if len(ranking_cache) > 256:
                stale_keys = [
                    key
                    for key, (exp, _ctx) in ranking_cache.items()
                    if exp <= now
                ]
                for key in stale_keys:
                    ranking_cache.pop(key, None)

    def _invalidate_ranking_cache_for_namespace(namespace: str) -> None:
        if not namespace:
            return
        with ranking_cache_lock:
            keys = [key for key in ranking_cache.keys() if len(key) > 2 and key[2] == namespace]
            for key in keys:
                ranking_cache.pop(key, None)

    def _invalidate_ranking_cache_for_current_user() -> None:
        _invalidate_ranking_cache_for_namespace(_current_ranking_cache_namespace())

    def _csrf_token_value() -> str:
        token = session.get(CSRF_FIELD_NAME)
        if isinstance(token, str) and token.strip():
            return token
        token = token_urlsafe(32)
        session[CSRF_FIELD_NAME] = token
        return token

    def _csrf_input() -> Markup:
        token = _csrf_token_value()
        return Markup(
            f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{token}">'
        )

    def _client_ip() -> str:
        forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or "unknown"
        return request.remote_addr or "unknown"

    def _login_rate_limit_window_seconds() -> int:
        return _env_int("OPCOES_LOGIN_WINDOW_SECONDS", 900, 60)

    def _login_rate_limit_block_seconds() -> int:
        return _env_int("OPCOES_LOGIN_BLOCK_SECONDS", 900, 60)

    def _login_rate_limit_max_attempts() -> int:
        return _env_int("OPCOES_LOGIN_MAX_ATTEMPTS", 5, 1)

    def _login_rate_limit_message(blocked_for_seconds: int) -> str:
        minutes = max(1, math.ceil(float(blocked_for_seconds) / 60.0))
        return (
            "Muitas tentativas de login deste IP. "
            f"Aguarde cerca de {minutes} minuto(s) e tente novamente."
        )

    def _prune_login_attempts(now: float) -> None:
        stale_keys = []
        window = float(_login_rate_limit_window_seconds())
        for key, state in login_attempts.items():
            blocked_until = float(state.get("blocked_until") or 0.0)
            first_failure_at = float(state.get("first_failure_at") or 0.0)
            if blocked_until > now:
                continue
            if (first_failure_at + window) > now:
                continue
            stale_keys.append(key)
        for key in stale_keys:
            login_attempts.pop(key, None)

    def _login_block_remaining_seconds() -> int | None:
        key = _client_ip()
        now = time.monotonic()
        with login_attempts_lock:
            _prune_login_attempts(now)
            state = login_attempts.get(key)
            if not state:
                return None
            blocked_until = float(state.get("blocked_until") or 0.0)
            if blocked_until <= now:
                return None
            return max(1, math.ceil(blocked_until - now))

    def _record_failed_login() -> int | None:
        key = _client_ip()
        now = time.monotonic()
        window = float(_login_rate_limit_window_seconds())
        block_seconds = float(_login_rate_limit_block_seconds())
        max_attempts = _login_rate_limit_max_attempts()
        with login_attempts_lock:
            _prune_login_attempts(now)
            state = login_attempts.get(key)
            if not state or (float(state.get("first_failure_at") or 0.0) + window) <= now:
                state = {
                    "count": 0,
                    "first_failure_at": now,
                    "blocked_until": 0.0,
                }
            count = int(state.get("count") or 0) + 1
            state["count"] = count
            if count >= max_attempts:
                state["count"] = 0
                state["first_failure_at"] = now
                state["blocked_until"] = now + block_seconds
            login_attempts[key] = state
            blocked_until = float(state.get("blocked_until") or 0.0)
            if blocked_until <= now:
                return None
            return max(1, math.ceil(blocked_until - now))

    def _clear_failed_login() -> None:
        key = _client_ip()
        with login_attempts_lock:
            login_attempts.pop(key, None)

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = _env_bool(
        "OPCOES_SESSION_COOKIE_SECURE", False
    )
    app.config["SESSION_COOKIE_SAMESITE"] = (
        os.getenv("OPCOES_SESSION_COOKIE_SAMESITE", "Lax") or "Lax"
    ).strip()
    # Session cookie (sem remember-me): ao fechar navegador, exige login novamente.
    app.config["SESSION_PERMANENT"] = False

    def _is_auth_enabled() -> bool:
        raw = os.getenv("OPCOES_AUTH_ENABLED", "1").strip().lower()
        return raw not in {"0", "false", "no", "off", "nao", "não"}

    def _safe_redirect_target(value: str | None) -> str:
        if not value:
            return url_for("index")
        candidate = value.strip()
        if not candidate.startswith("/") or candidate.startswith("//"):
            return url_for("index")
        if candidate.startswith("/login") or candidate.startswith("/logout"):
            return url_for("index")
        return candidate

    @app.before_request
    def _protect_csrf():
        if app.testing:
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if (request.endpoint or "") == "static":
            return None
        expected = session.get(CSRF_FIELD_NAME)
        provided = (
            request.form.get(CSRF_FIELD_NAME)
            or request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
        )
        if not expected or not provided:
            return (
                "Formulario expirado ou invalido. Recarregue a pagina e tente novamente.",
                400,
            )
        if not compare_digest(str(expected), str(provided)):
            return (
                "Formulario expirado ou invalido. Recarregue a pagina e tente novamente.",
                400,
            )
        return None

    @app.before_request
    def _bind_user_context():
        g.pg_schema_override_token = None
        g.current_username = None

        if app.testing or not _is_auth_enabled():
            return None

        endpoint = request.endpoint or ""
        if endpoint in {"login", "logout", "static"}:
            return None

        username = normalize_username(session.get("username") or "")
        if not username:
            next_url = (
                request.full_path
                if request.full_path and request.full_path != "/?"
                else request.path
            )
            return redirect(url_for("login", next=next_url))

        now_ts = _utc_now_ts()
        idle_timeout_seconds = _session_idle_timeout_seconds()
        raw_last_activity = session.get("last_activity_at")
        try:
            last_activity_ts = (
                int(raw_last_activity) if raw_last_activity is not None else None
            )
        except (TypeError, ValueError):
            last_activity_ts = None

        if (
            last_activity_ts is not None
            and (now_ts - last_activity_ts) > idle_timeout_seconds
        ):
            next_url = (
                request.full_path
                if request.full_path and request.full_path != "/?"
                else request.path
            )
            session.clear()
            return redirect(url_for("login", next=next_url, reason="expired"))

        if "session_started_at" not in session:
            session["session_started_at"] = now_ts
        # Sliding session: renova enquanto usuário estiver ativo.
        session["last_activity_at"] = now_ts

        g.pg_schema_override_token = set_pg_schema_override(username)
        g.current_username = username
        return None

    @app.teardown_request
    def _clear_user_context(_exc):
        pg_token = getattr(g, "pg_schema_override_token", None)
        if pg_token is not None:
            reset_pg_schema_override(pg_token)
            g.pg_schema_override_token = None

    @app.after_request
    def _invalidate_ranking_cache_after_write(response):
        endpoint = request.endpoint or ""
        if request.method == "POST" and endpoint in ranking_cache_write_endpoints:
            _invalidate_ranking_cache_for_current_user()
        if endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")
            response.headers.setdefault(
                "Referrer-Policy", "strict-origin-when-cross-origin"
            )
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )
            response.headers.setdefault(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "base-uri 'self'; "
                    "form-action 'self'; "
                    "frame-ancestors 'none'; "
                    "object-src 'none'; "
                    "img-src 'self' data: https:; "
                    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "font-src 'self' data: https://cdn.jsdelivr.net; "
                    "connect-src 'self';"
                ),
            )
            if request.is_secure:
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        return response

    @app.context_processor
    def _inject_user_context():
        auth_active = not app.testing and _is_auth_enabled()
        return {
            "auth_enabled": auth_active,
            "current_username": (
                normalize_username(session.get("username") or "") if auth_active else ""
            ),
            "csrf_token": _csrf_token_value,
            "csrf_input": _csrf_input,
        }

    @app.route("/login", methods=["GET", "POST"])
    def login() -> str:
        if app.testing or not _is_auth_enabled():
            return redirect(url_for("index"))

        error = None
        if request.method == "GET" and request.args.get("reason") == "expired":
            error = "Sessão expirada por inatividade. Entre novamente."
        next_url = _safe_redirect_target(request.values.get("next"))
        if request.method == "POST":
            blocked_for = _login_block_remaining_seconds()
            if blocked_for is not None:
                return (
                    render_template(
                        "login.html",
                        error=_login_rate_limit_message(blocked_for),
                        next_url=next_url,
                    ),
                    429,
                )
            username = normalize_username(request.form.get("username") or "")
            password = request.form.get("password") or ""
            if authenticate_user(username=username, password=password):
                _clear_failed_login()
                session.clear()
                session["username"] = username
                now_ts = _utc_now_ts()
                session["session_started_at"] = now_ts
                session["last_activity_at"] = now_ts
                return redirect(next_url)
            error = "Usuário ou senha inválidos."

        if request.method == "POST" and error:
            blocked_for = _record_failed_login()
            if blocked_for is not None:
                return (
                    render_template(
                        "login.html",
                        error=_login_rate_limit_message(blocked_for),
                        next_url=next_url,
                    ),
                    429,
                )
        return render_template("login.html", error=error, next_url=next_url)

    @app.post("/logout")
    def logout():
        _invalidate_ranking_cache_for_namespace(
            _ranking_cache_namespace(session.get("username"))
        )
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index() -> str:
        cache_key = _ranking_cache_key()
        ctx = _get_ranking_cache(cache_key)
        if ctx is None:
            ctx = get_ranking_context(request.args)
            _set_ranking_cache(cache_key, ctx)
        return render_template("index.html", **ctx)

    @app.route("/covered-call")
    def covered_call() -> str:
        ctx = get_covered_call_context(request.args)
        return render_template("covered_call.html", **ctx)

    @app.route("/cash-covered-put")
    def cash_covered_put() -> str:
        ctx = get_cash_covered_put_context(request.args)
        return render_template("cash_covered_put.html", **ctx)

    @app.route("/fundamentus")
    def fundamentus() -> str:
        ctx = get_fundamentus_context(request.args)
        return render_template("fundamentus.html", **ctx)

    @app.route("/darf")
    def darf_view() -> str:
        mode = (request.args.get("mode") or "real").strip().lower()
        is_simulated = mode == "simulated"
        selected_period = (request.args.get("period") or "").strip()

        provisions = darf.get_monthly_darf_provisions(is_simulated=is_simulated, limit=36)
        records = darf.list_months(is_simulated=is_simulated, limit=36)
        record_by_period = {r.period: r for r in records}
        tax_periods = sorted(
            {
                f"{today.year:04d}-{today.month:02d}"
                for today in [datetime.date.today()]
            }
            | set(provisions.keys())
            | set(record_by_period.keys()),
            reverse=True,
        )
        if not tax_periods:
            today = datetime.date.today()
            tax_periods = [today.strftime("%Y-%m")]

        # Garante uma janela recente para o usuário conseguir navegar mesmo sem lançamentos.
        anchor_year = int(tax_periods[0][:4])
        anchor_month = int(tax_periods[0][5:7])
        recent_periods: list[str] = []
        year = anchor_year
        month = anchor_month
        for _ in range(12):
            recent_periods.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods = sorted(set(recent_periods) | set(tax_periods), reverse=True)

        tax_summaries = list_monthly_tax_summaries(
            periods=periods,
            is_simulated=is_simulated,
        )
        tax_by_period = {summary.period: summary for summary in tax_summaries}

        if not selected_period:
            if periods:
                selected_period = periods[0]
            else:
                selected_period = datetime.date.today().strftime("%Y-%m")

        summaries = []
        for p in periods:
            tax_summary = tax_by_period.get(p) or compute_tax(
                month=int(p[5:7]),
                year=int(p[:4]),
                is_simulated=is_simulated,
            )
            prov = float(provisions.get(p, 0.0) or 0.0)
            rec = record_by_period.get(p)
            try:
                due_date = rec.due_date if rec else darf.last_business_day_next_month(p)
            except Exception:
                due_date = "-"

            generated = rec.amount if rec else None
            paid_date = rec.paid_date if rec else None
            paid_amount = rec.paid_amount if rec else None
            tax_due = float(tax_summary.net_ir_due or 0.0)

            status = "Sem movimento"
            if tax_due > 0 and not rec:
                status = "Pendente"
            if rec and not rec.paid_date:
                status = "Gerado"
            if rec and rec.paid_date:
                status = "Pago"

            diff = None
            if rec is not None:
                diff = tax_due - float(rec.amount or 0.0)

            summaries.append(
                {
                    "period": p,
                    "tax_summary": tax_summary,
                    "tax_due": tax_due,
                    "provisioned": prov,
                    "generated": generated,
                    "due_date": due_date,
                    "paid_date": paid_date,
                    "paid_amount": paid_amount,
                    "status": status,
                    "diff": diff,
                }
            )

        selected_record = None
        try:
            selected_record = darf.get_month(
                period=selected_period, is_simulated=is_simulated
            )
        except Exception:
            selected_record = None

        provision_entries = []
        try:
            provision_entries = darf.list_provision_entries(period=selected_period, is_simulated=is_simulated)
        except Exception:
            provision_entries = []

        selected_tax = tax_by_period.get(selected_period)
        if selected_tax is None:
            selected_tax = compute_tax(
                month=int(selected_period[5:7]),
                year=int(selected_period[:4]),
                is_simulated=is_simulated,
            )
        selected_tax_events = list_tax_events_for_period(
            period=selected_period,
            is_simulated=is_simulated,
        )
        selected_provisioned = float(provisions.get(selected_period, 0.0) or 0.0)

        return render_template(
            "darf.html",
            mode=mode,
            is_simulated=is_simulated,
            selected_period=selected_period,
            periods=summaries,
            selected_tax=selected_tax,
            selected_tax_events=selected_tax_events,
            selected_provisioned=selected_provisioned,
            provision_entries=provision_entries,
            selected_record=selected_record,
        )

    @app.post("/darf/generate")
    def darf_generate():
        form = request.form
        period = (form.get("period") or "").strip()
        is_simulated = form.get("is_simulated") == "1"
        mode = "simulated" if is_simulated else "real"

        try:
            summary = compute_tax(
                month=int(period[5:7]),
                year=int(period[:4]),
                is_simulated=is_simulated,
            )
            due_date = darf.last_business_day_next_month(period)
        except Exception:
            return redirect(url_for("darf_view", mode=mode))

        if summary.net_ir_due > 0:
            darf.upsert_month(
                period=period,
                due_date=due_date,
                amount=summary.net_ir_due,
                is_simulated=is_simulated,
            )
        else:
            darf.delete_month(
                period=period,
                is_simulated=is_simulated,
                only_unpaid=True,
            )

        return redirect(url_for("darf_view", mode=mode, period=period))

    @app.post("/darf/pay")
    def darf_pay():
        form = request.form
        period = (form.get("period") or "").strip()
        is_simulated = form.get("is_simulated") == "1"
        mode = "simulated" if is_simulated else "real"
        paid_date = (
            _parse_form_date(form.get("paid_date")) or datetime.date.today().isoformat()
        )
        paid_amount = (
            _parse_form_float(form.get("paid_amount"))
            if form.get("paid_amount")
            else None
        )

        try:
            rec = darf.get_month(period=period, is_simulated=is_simulated)
            if not rec:
                summary = compute_tax(
                    month=int(period[5:7]),
                    year=int(period[:4]),
                    is_simulated=is_simulated,
                )
                if summary.net_ir_due <= 0:
                    return redirect(url_for("darf_view", mode=mode, period=period))
                due_date = darf.last_business_day_next_month(period)
                darf.upsert_month(
                    period=period,
                    due_date=due_date,
                    amount=summary.net_ir_due,
                    is_simulated=is_simulated,
                )
            darf.mark_paid(
                period=period,
                paid_date=paid_date,
                paid_amount=paid_amount,
                is_simulated=is_simulated,
            )
        except Exception:
            return redirect(url_for("darf_view", mode=mode, period=period))

        return redirect(url_for("darf_view", mode=mode, period=period))

    @app.post("/finance/add")
    def finance_add():
        form = request.form
        amount = _parse_form_float(form.get("amount"))
        type_str = form.get("type")
        desc = form.get("description") or "Movimentação manual"
        date = form.get("date") or datetime.date.today().isoformat()
        is_simulated = form.get("is_simulated") == "1"

        # Valid transaction type
        try:
            tx_type = finance.TransactionType(type_str)
        except ValueError:
            return redirect(url_for("cash_covered_put"))  # Or error page

        # Negative amount for withdrawal
        if tx_type == finance.TransactionType.WITHDRAWAL and amount > 0:
            amount = -amount

        finance.add_transaction(
            date=date,
            type=tx_type,
            amount=amount,
            description=desc,
            is_simulated=is_simulated,
        )
        return redirect(url_for("cash_covered_put"))

    @app.post("/finance/assign")
    def finance_assign():
        form = request.form
        position_id = int(form.get("position_id"))
        strike = _parse_form_float(form.get("strike"))
        qty = int(form.get("qty"))
        date = form.get("date") or datetime.date.today().isoformat()
        assign_put(position_id=position_id, strike=strike, qty=qty, date=date)
        return redirect(url_for("cash_covered_put"))

    @app.post("/finance/callaway")
    def finance_callaway():
        form = request.form
        position_id = int(form.get("position_id"))
        date = _parse_form_date(form.get("date")) or datetime.date.today().isoformat()
        try:
            underlying = callaway(position_id=position_id, date=date)
        except FlowError as exc:
            if exc.underlying:
                return redirect(url_for("covered_call", underlying=exc.underlying))
            return redirect(url_for("covered_call"))

        if underlying:
            return redirect(url_for("covered_call", underlying=underlying))
        return redirect(url_for("covered_call"))

    @app.post("/finance/expire")
    def finance_expire():
        form = request.form
        try:
            position_id = int(form.get("position_id"))
        except (TypeError, ValueError):
            return redirect(url_for("positions"))

        date = _parse_form_date(form.get("date")) or datetime.date.today().isoformat()

        pos = get_position(position_id)
        if not pos:
            return redirect(url_for("positions"))

        ticker = pos.get("ticker")
        underlying = (pos.get("underlying") or "").strip().upper()
        opt_type = infer_option_type(ticker)

        if not underlying or (ticker and (str(ticker).strip().upper() == underlying)):
            return redirect(url_for("positions"))

        if (pos.get("status") or "").strip().lower() != "open":
            if opt_type == "PUT":
                return redirect(
                    url_for("cash_covered_put", underlying=underlying)
                    if underlying
                    else url_for("cash_covered_put")
                )
            if opt_type == "CALL":
                return redirect(
                    url_for("covered_call", underlying=underlying)
                    if underlying
                    else url_for("covered_call")
                )
            return redirect(url_for("positions"))

        if opt_type not in {"PUT", "CALL"}:
            return redirect(url_for("positions"))

        close_position(
            position_id=position_id,
            exit_date=date,
            exit_price=0.0,
            exit_reason="Expiração",
        )
        finance.sync_position_closure_effects(position_id=position_id)

        if opt_type == "PUT":
            return redirect(
                url_for("cash_covered_put", underlying=underlying)
                if underlying
                else url_for("cash_covered_put")
            )
        return redirect(
            url_for("covered_call", underlying=underlying)
            if underlying
            else url_for("covered_call")
        )

    @app.post("/finance/update/<int:tx_id>")
    def finance_update(tx_id: int):
        form = request.form
        date = form.get("date") or None
        type_str = form.get("type") or None
        desc = form.get("description") or None
        amount = _parse_form_float(form.get("amount"))
        is_simulated = form.get("is_simulated") == "1"

        tx_type = None
        if type_str:
            try:
                tx_type = finance.TransactionType(type_str)
            except ValueError:
                tx_type = None

        # mesma regra: retirada em valor positivo vira negativo
        if tx_type == finance.TransactionType.WITHDRAWAL and amount > 0:
            amount = -amount

        finance.update_transaction(
            tx_id,
            date=date,
            type=tx_type,
            amount=amount,
            description=desc,
            is_simulated=is_simulated,
        )
        return redirect(url_for("cash_covered_put"))

    @app.post("/finance/delete/<int:tx_id>")
    def finance_delete(tx_id: int):
        finance.delete_transaction(tx_id)
        return redirect(url_for("cash_covered_put"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_view() -> str:
        def _format_panel_datetime(
            value: object,
            *,
            tz: datetime.tzinfo = LOCAL_DISPLAY_TZ,
        ) -> str:
            if value is None:
                return "-"
            if isinstance(value, datetime.datetime):
                current = value
            else:
                return str(value)
            if current.tzinfo is None:
                current = current.replace(tzinfo=datetime.timezone.utc)
            localized = current.astimezone(tz)
            return localized.strftime("%d/%m/%Y %H:%M")

        def _format_duration(seconds: object) -> str:
            if seconds is None:
                return "-"
            try:
                total = max(int(seconds), 0)
            except (TypeError, ValueError):
                return "-"
            if total < 60:
                return f"{total}s"
            minutes, rem_seconds = divmod(total, 60)
            if minutes < 60:
                return f"{minutes}m {rem_seconds:02d}s"
            hours, rem_minutes = divmod(minutes, 60)
            return f"{hours}h {rem_minutes:02d}m"

        def _status_meta(status: object) -> tuple[str, str]:
            normalized = str(status or "").strip().lower()
            mapping = {
                "running": ("Em andamento", "text-bg-warning"),
                "success": ("Concluido", "text-bg-success"),
                "failed": ("Falhou", "text-bg-danger"),
            }
            return mapping.get(normalized, ("Sem registro", "text-bg-secondary"))

        if request.method == "POST":
            form = request.form

            # Fee Settings
            equity_fixed = _parse_form_float(form.get("equity_fixed"))
            equity_percent = _parse_form_float(form.get("equity_percent"))
            option_fixed = _parse_form_float(form.get("option_fixed"))
            option_percent_notional = _parse_form_float(
                form.get("option_percent_notional")
            )
            update_fee_settings(
                equity_fixed=equity_fixed,
                equity_percent=equity_percent,
                option_fixed=option_fixed,
                option_percent_notional=option_percent_notional,
            )

            # Strategy Settings
            min_score = int(form.get("strat_min_score", 8))
            limit_opp = int(form.get("strat_limit_opportunities", 30))
            recur_days = int(form.get("strat_recurring_days", 30))
            update_strategy_settings(
                min_score=min_score,
                limit_opportunities=limit_opp,
                recurring_days=recur_days,
            )

            fund_cfg = get_fundamentus_settings()

            def _form_float_or_default(name: str, current: float) -> float:
                raw = form.get(name)
                if raw is None or not str(raw).strip():
                    return current
                return _parse_form_float(raw)

            update_fundamentus_settings(
                target_yield_pct=_form_float_or_default(
                    "fund_target_yield_pct", fund_cfg.target_yield_pct
                ),
                put_distance_limit_pct=_form_float_or_default(
                    "fund_put_distance_limit_pct",
                    fund_cfg.put_distance_limit_pct,
                ),
                put_min_premium_pct=_form_float_or_default(
                    "fund_put_min_premium_pct",
                    fund_cfg.put_min_premium_pct,
                ),
                put_target_monthly_yield_pct=_form_float_or_default(
                    "fund_put_target_monthly_yield_pct",
                    fund_cfg.put_target_monthly_yield_pct,
                ),
                put_min_score=_form_float_or_default(
                    "fund_put_min_score", fund_cfg.put_min_score
                ),
            )

            cash_put_cfg = get_cash_put_settings()
            buyback_raw = form.get("cash_put_buyback_target_pct")
            if buyback_raw and buyback_raw.strip():
                buyback_target_pct = _parse_form_float(buyback_raw)
            else:
                buyback_target_pct = cash_put_cfg.buyback_target_pct
            update_cash_put_settings(
                underlying=cash_put_cfg.underlying,
                min_yield_pct=cash_put_cfg.min_yield_pct,
                min_buffer_pct=cash_put_cfg.min_buffer_pct,
                min_days=cash_put_cfg.min_days,
                max_days=cash_put_cfg.max_days,
                contract_size=cash_put_cfg.contract_size,
                limit=cash_put_cfg.limit,
                cash_mode=cash_put_cfg.cash_mode,
                buyback_target_pct=buyback_target_pct,
            )

            ccall_cfg = get_covered_call_settings()
            ccall_buyback_raw = form.get("ccall_buyback_target_pct")
            if ccall_buyback_raw and ccall_buyback_raw.strip():
                ccall_buyback_target_pct = _parse_form_float(ccall_buyback_raw)
            else:
                ccall_buyback_target_pct = ccall_cfg.buyback_target_pct
            update_covered_call_settings(
                underlying=ccall_cfg.underlying,
                min_extrinsic=ccall_cfg.min_extrinsic,
                min_days=ccall_cfg.min_days,
                max_days=ccall_cfg.max_days,
                min_dist_strike=ccall_cfg.min_dist_strike,
                buyback_target_pct=ccall_buyback_target_pct,
                only_target_hits=ccall_cfg.only_target_hits,
            )

            return redirect(url_for("settings_view"))

        fees_cfg: FeeSettings = get_fee_settings()
        strat_cfg: StrategySettings = get_strategy_settings()
        fund_cfg: FundamentusSettings = get_fundamentus_settings()
        ccall_cfg: CoveredCallSettings = get_covered_call_settings()
        cash_put_cfg: CashCoveredPutSettings = get_cash_put_settings()
        automation_dashboard = get_service_dashboard(limit=12)

        automation_services = []
        for service in automation_dashboard.get("services", []):
            last_run = service.get("last_run")
            last_run_view = None
            if isinstance(last_run, dict):
                status_label, status_class = _status_meta(last_run.get("status"))
                last_run_view = {
                    "status_label": status_label,
                    "status_class": status_class,
                    "started_at_display": _format_panel_datetime(last_run.get("started_at")),
                    "finished_at_display": _format_panel_datetime(last_run.get("finished_at")),
                    "duration_display": _format_duration(last_run.get("duration_seconds")),
                    "summary": (last_run.get("summary") or "").strip(),
                    "error_message": (last_run.get("error_message") or "").strip(),
                }
            automation_services.append(
                {
                    **service,
                    "next_run_local_display": _format_panel_datetime(service.get("next_run_local")),
                    "next_run_utc_display": _format_panel_datetime(
                        service.get("next_run_utc"),
                        tz=datetime.timezone.utc,
                    ),
                    "last_run_view": last_run_view,
                }
            )

        automation_runs = []
        for row in automation_dashboard.get("recent_runs", []):
            status_label, status_class = _status_meta(row.get("status"))
            automation_runs.append(
                {
                    **row,
                    "status_label": status_label,
                    "status_class": status_class,
                    "started_at_display": _format_panel_datetime(row.get("started_at")),
                    "finished_at_display": _format_panel_datetime(row.get("finished_at")),
                    "duration_display": _format_duration(row.get("duration_seconds")),
                    "summary_display": (row.get("summary") or "").strip(),
                    "error_display": (row.get("error_message") or "").strip(),
                }
            )
        return render_template(
            "settings.html",
            fees=fees_cfg,
            strat=strat_cfg,
            fund=fund_cfg,
            covered_call=ccall_cfg,
            cash_put=cash_put_cfg,
            automation_services=automation_services,
            automation_runs=automation_runs,
        )

    @app.route("/positions")
    def positions() -> str:
        ticker_contains = (request.args.get("ticker") or "").strip().upper()
        underlying_contains = (request.args.get("underlying") or "").strip().upper()
        strategy_tag = (request.args.get("strategy_tag") or "").strip()
        trade_type = (request.args.get("trade_type") or "").strip().lower()
        status = (request.args.get("status") or "all").strip().lower()
        is_simulated_raw = (request.args.get("is_simulated") or "").strip()
        result_year_raw = (request.args.get("result_year") or "").strip()
        result_month_raw = (request.args.get("result_month") or "").strip()

        include_closed = True
        only_closed = False
        if status == "open":
            include_closed = False
        elif status == "closed":
            only_closed = True

        is_simulated = None
        if is_simulated_raw in {"0", "1"}:
            is_simulated = is_simulated_raw == "1"

        result_year = None
        if result_year_raw:
            try:
                result_year = int(result_year_raw)
            except ValueError:
                result_year = None

        result_month = None
        if result_month_raw:
            try:
                month_candidate = int(result_month_raw)
            except ValueError:
                month_candidate = None
            if month_candidate is not None and 1 <= month_candidate <= 12:
                result_month = month_candidate

        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = request.path

        positions = list_positions(
            include_closed=include_closed,
            only_closed=only_closed,
            ticker_contains=ticker_contains or None,
            underlying_contains=underlying_contains or None,
            strategy_tag=strategy_tag or None,
            trade_type=trade_type or None,
            is_simulated=is_simulated,
        )
        position_ids = [int(p["id"]) for p in positions if p.get("id") is not None]
        premium_ids = finance.get_premium_position_ids(position_ids)
        for pos in positions:
            pos_id = pos.get("id")
            pos["premium_recorded"] = bool(pos_id and int(pos_id) in premium_ids)
        realized_summary = summarize_realized_positions(
            ticker_contains=ticker_contains or None,
            underlying_contains=underlying_contains or None,
            strategy_tag=strategy_tag or None,
            trade_type=trade_type or None,
            is_simulated=is_simulated,
            selected_year=result_year,
            selected_month=result_month,
        )
        return render_template(
            "positions.html",
            positions=positions,
            filter_ticker=ticker_contains,
            filter_underlying=underlying_contains,
            filter_strategy_tag=strategy_tag,
            filter_trade_type=trade_type,
            filter_status=status,
            filter_is_simulated=is_simulated_raw,
            realized_summary=realized_summary,
            next_url=next_url,
        )

    @app.route("/audit")
    def audit_view() -> str:
        mode = (request.args.get("mode") or "real").strip().lower()
        include_closed = (request.args.get("include_closed") or "1") == "1"

        is_simulated: Optional[bool]
        if mode == "simulated":
            is_simulated = True
        elif mode == "all":
            is_simulated = None
        else:
            mode = "real"
            is_simulated = False

        positions_all = list_positions(include_closed=True)
        if is_simulated is not None:
            positions_all = [
                p for p in positions_all if bool(p.get("is_simulated")) == is_simulated
            ]

        children_by_parent: dict[int, list[dict]] = {}
        for pos in positions_all:
            parent_id = pos.get("parent_position_id")
            if parent_id is None:
                continue
            try:
                key = int(parent_id)
            except (TypeError, ValueError):
                continue
            children_by_parent.setdefault(key, []).append(pos)

        ledger_sums = finance.get_ledger_sums_by_position(
            types=[
                finance.TransactionType.PREMIUM,
                finance.TransactionType.DARF,
                finance.TransactionType.BUY,
                finance.TransactionType.ASSIGNMENT,
                finance.TransactionType.REALIZED,
            ],
            is_simulated=is_simulated,
        )

        def _money_diff(
            actual: Optional[float], expected: Optional[float]
        ) -> Optional[float]:
            if actual is None and expected is None:
                return None
            return round(float(actual or 0.0) - float(expected or 0.0), 2)

        rows = []
        totals = {
            "expected_premium": 0.0,
            "expected_darf": 0.0,
            "expected_buyback": 0.0,
            "actual_premium": 0.0,
            "actual_darf": 0.0,
            "actual_buyback": 0.0,
            "expected_net": 0.0,
            "actual_net": 0.0,
            "expected_cash_net": 0.0,
            "actual_cash_net": 0.0,
            "expected_assignment": 0.0,
            "actual_assignment": 0.0,
            "expected_total_cash": 0.0,
            "actual_total_cash": 0.0,
            "expected_realized": 0.0,
            "actual_realized": 0.0,
        }

        for pos in positions_all:
            if (
                not include_closed
                and (pos.get("status") or "").strip().lower() == "closed"
            ):
                continue

            pid = int(pos.get("id") or 0)
            ticker = (pos.get("ticker") or "").strip()
            underlying = (pos.get("underlying") or "").strip()
            is_option = _is_option_ticker(ticker)
            side = (pos.get("side") or "").strip().lower()
            trade_type = (pos.get("trade_type") or "swing").strip().lower()
            entry_price = float(pos.get("entry_price") or 0.0)
            qty = int(pos.get("qty") or 0)
            fees = float(pos.get("fees") or 0.0)
            partial_qty = int(pos.get("partial_qty") or 0)
            close_qty = max(qty - partial_qty, 0)
            status_norm = (pos.get("status") or "").strip().lower()
            exit_price_raw = pos.get("exit_price")
            exit_price = float(exit_price_raw) if exit_price_raw is not None else None

            expected_premium = None
            expected_darf = None
            expected_buyback = None
            expected_assignment = None
            expected_realized = None
            assignment_stock_ticker = None
            assignment_stock_qty = 0
            assignment_stock_price = None
            realized_events = build_position_tax_events(pos)
            if realized_events:
                expected_realized = round(
                    sum(float(event.amount) for event in realized_events),
                    2,
                )
            if is_option and side == "short":
                expected_premium = finance.calculate_option_premium(
                    entry_price=entry_price,
                    qty=qty,
                    fees=fees,
                )
                expected_darf = finance.calculate_darf_provision(
                    premium_amount=expected_premium,
                    trade_type=trade_type,
                )
                if status_norm == "closed" and exit_price is not None and close_qty > 0:
                    expected_buyback = -round(float(exit_price) * int(close_qty), 2)
                if (
                    infer_option_type(ticker) == "PUT"
                    and status_norm == "closed"
                    and "exerc" in ((pos.get("exit_reason") or "").strip().lower())
                ):
                    child_positions = children_by_parent.get(pid, [])
                    stock_children = [
                        child
                        for child in child_positions
                        if (child.get("ticker") or "").strip().upper()
                        == (underlying or "").strip().upper()
                    ]
                    if stock_children:
                        total_stock_cost = 0.0
                        for child in stock_children:
                            child_qty = int(child.get("qty") or 0)
                            child_price = float(child.get("entry_price") or 0.0)
                            assignment_stock_qty += child_qty
                            total_stock_cost += child_qty * child_price
                        if assignment_stock_qty > 0:
                            assignment_stock_ticker = (underlying or "").strip().upper()
                            assignment_stock_price = total_stock_cost / assignment_stock_qty
                            expected_assignment = -round(total_stock_cost, 2)

            actual_premium = ledger_sums.get(pid, {}).get(
                finance.TransactionType.PREMIUM.value
            )
            actual_darf = ledger_sums.get(pid, {}).get(
                finance.TransactionType.DARF.value
            )
            actual_buyback = ledger_sums.get(pid, {}).get(
                finance.TransactionType.BUY.value
            )
            actual_assignment = ledger_sums.get(pid, {}).get(
                finance.TransactionType.ASSIGNMENT.value
            )
            actual_realized = ledger_sums.get(pid, {}).get(
                finance.TransactionType.REALIZED.value
            )

            if (
                expected_premium is None
                and actual_premium is None
                and actual_darf is None
                and expected_buyback is None
                and actual_buyback is None
                and expected_assignment is None
                and actual_assignment is None
                and expected_realized is None
                and actual_realized is None
            ):
                continue

            expected_net = None
            actual_net = None
            expected_cash_net = None
            actual_cash_net = None
            expected_total_cash = None
            actual_total_cash = None
            if (
                expected_premium is not None
                or expected_darf is not None
                or expected_buyback is not None
                or expected_assignment is not None
            ):
                expected_net = float(expected_premium or 0.0) + float(
                    expected_darf or 0.0
                )
                expected_cash_net = expected_net + float(expected_buyback or 0.0)
                expected_total_cash = expected_cash_net + float(
                    expected_assignment or 0.0
                )
            if (
                actual_premium is not None
                or actual_darf is not None
                or actual_buyback is not None
                or actual_assignment is not None
            ):
                actual_net = float(actual_premium or 0.0) + float(actual_darf or 0.0)
                actual_cash_net = actual_net + float(actual_buyback or 0.0)
                actual_total_cash = actual_cash_net + float(actual_assignment or 0.0)

            rows.append(
                {
                    "id": pid,
                    "ticker": ticker,
                    "underlying": underlying,
                    "side": side,
                    "status": pos.get("status"),
                    "qty": qty,
                    "entry_price": entry_price,
                    "fees": fees,
                    "trade_type": trade_type,
                    "expected_premium": expected_premium,
                    "expected_darf": expected_darf,
                    "expected_buyback": expected_buyback,
                    "expected_assignment": expected_assignment,
                    "expected_realized": expected_realized,
                    "actual_premium": actual_premium,
                    "actual_darf": actual_darf,
                    "actual_buyback": actual_buyback,
                    "actual_assignment": actual_assignment,
                    "actual_realized": actual_realized,
                    "diff_premium": _money_diff(actual_premium, expected_premium),
                    "diff_darf": _money_diff(actual_darf, expected_darf),
                    "diff_buyback": _money_diff(actual_buyback, expected_buyback),
                    "diff_assignment": _money_diff(
                        actual_assignment, expected_assignment
                    ),
                    "diff_realized": _money_diff(actual_realized, expected_realized),
                    "expected_net": expected_net,
                    "actual_net": actual_net,
                    "diff_net": _money_diff(actual_net, expected_net),
                    "expected_cash_net": expected_cash_net,
                    "actual_cash_net": actual_cash_net,
                    "diff_cash_net": _money_diff(actual_cash_net, expected_cash_net),
                    "expected_total_cash": expected_total_cash,
                    "actual_total_cash": actual_total_cash,
                    "diff_total_cash": _money_diff(
                        actual_total_cash, expected_total_cash
                    ),
                    "assignment_stock_ticker": assignment_stock_ticker,
                    "assignment_stock_qty": assignment_stock_qty,
                    "assignment_stock_price": assignment_stock_price,
                }
            )

            if expected_premium is not None:
                totals["expected_premium"] += float(expected_premium or 0.0)
            if expected_darf is not None:
                totals["expected_darf"] += float(expected_darf or 0.0)
            if expected_buyback is not None:
                totals["expected_buyback"] += float(expected_buyback or 0.0)
            if actual_premium is not None:
                totals["actual_premium"] += float(actual_premium or 0.0)
            if actual_darf is not None:
                totals["actual_darf"] += float(actual_darf or 0.0)
            if actual_buyback is not None:
                totals["actual_buyback"] += float(actual_buyback or 0.0)
            if expected_assignment is not None:
                totals["expected_assignment"] += float(expected_assignment or 0.0)
            if actual_assignment is not None:
                totals["actual_assignment"] += float(actual_assignment or 0.0)
            if expected_realized is not None:
                totals["expected_realized"] += float(expected_realized or 0.0)
            if actual_realized is not None:
                totals["actual_realized"] += float(actual_realized or 0.0)

        totals["expected_net"] = totals["expected_premium"] + totals["expected_darf"]
        totals["actual_net"] = totals["actual_premium"] + totals["actual_darf"]
        totals["expected_cash_net"] = (
            totals["expected_net"] + totals["expected_buyback"]
        )
        totals["actual_cash_net"] = totals["actual_net"] + totals["actual_buyback"]
        totals["expected_total_cash"] = (
            totals["expected_cash_net"] + totals["expected_assignment"]
        )
        totals["actual_total_cash"] = (
            totals["actual_cash_net"] + totals["actual_assignment"]
        )

        position_ids = {int(p.get("id") or 0) for p in positions_all}
        orphan_rows = [
            {
                "id": pid,
                "actual_premium": sums.get(finance.TransactionType.PREMIUM.value),
                "actual_darf": sums.get(finance.TransactionType.DARF.value),
                "actual_buyback": sums.get(finance.TransactionType.BUY.value),
                "actual_assignment": sums.get(finance.TransactionType.ASSIGNMENT.value),
                "actual_realized": sums.get(finance.TransactionType.REALIZED.value),
                "actual_net": (sums.get(finance.TransactionType.PREMIUM.value) or 0.0)
                + (sums.get(finance.TransactionType.DARF.value) or 0.0),
                "actual_cash_net": (
                    sums.get(finance.TransactionType.PREMIUM.value) or 0.0
                )
                + (sums.get(finance.TransactionType.DARF.value) or 0.0)
                + (sums.get(finance.TransactionType.BUY.value) or 0.0),
                "actual_total_cash": (
                    (sums.get(finance.TransactionType.PREMIUM.value) or 0.0)
                    + (sums.get(finance.TransactionType.DARF.value) or 0.0)
                    + (sums.get(finance.TransactionType.BUY.value) or 0.0)
                    + (sums.get(finance.TransactionType.ASSIGNMENT.value) or 0.0)
                ),
            }
            for pid, sums in ledger_sums.items()
            if pid not in position_ids
            and (
                sums.get(finance.TransactionType.PREMIUM.value) is not None
                or sums.get(finance.TransactionType.DARF.value) is not None
                or sums.get(finance.TransactionType.BUY.value) is not None
                or sums.get(finance.TransactionType.ASSIGNMENT.value) is not None
                or sums.get(finance.TransactionType.REALIZED.value) is not None
            )
        ]

        return render_template(
            "audit.html",
            rows=rows,
            totals=totals,
            mode=mode,
            include_closed=include_closed,
            orphan_rows=orphan_rows,
        )

    @app.post("/positions/add")
    def add_position_view():
        form = request.form
        ticker = form.get("ticker", "").strip()
        underlying_input = form.get("underlying", "").strip()
        is_simulated = form.get("is_simulated") == "1"
        qty = int(form.get("qty", 0) or 0)
        entry_price = _parse_form_float(form.get("entry_price"))
        fees_input = form.get("fees")
        parent_raw = form.get("parent_position_id")
        parent_id = int(parent_raw) if parent_raw and parent_raw.strip() else None
        side_raw = (form.get("side") or "").strip()
        if not side_raw:
            # Se marcou prêmio, assume venda (short). Caso contrário, default long.
            side_raw = "short" if form.get("record_premium") == "1" else "long"
        strategy_tag_raw = form.get("strategy_tag") or None
        side_raw = _normalize_form_side(
            ticker=ticker,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
            record_premium=form.get("record_premium") == "1",
        )
        underlying = _resolve_underlying_for_position(
            ticker=ticker,
            underlying=underlying_input,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
        )
        if fees_input:
            fees = _parse_form_float(fees_input)
        else:
            fees = _auto_fees(
                ticker=ticker,
                underlying=underlying or ticker,
                qty=qty,
                entry_price=entry_price,
            )

        pos_id = add_position(
            ticker=ticker,
            underlying=underlying,
            trade_date=form.get("trade_date", ""),
            qty=qty,
            entry_price=entry_price,
            fees=fees,
            trade_type=form.get("trade_type", "swing"),
            side=side_raw,
            irrf=float(form["irrf"]) if form.get("irrf") else None,
            notes=form.get("notes") or None,
            is_simulated=is_simulated,
            parent_position_id=parent_id,
            strategy_tag=strategy_tag_raw,
        )

        # Registro opcional: prêmio no caixa (venda) + provisão DARF (saldo limpo).
        if entry_price > 0 and qty > 0 and form.get("record_premium") == "1":
            t = (ticker or "").strip().upper()
            is_option = _is_option_ticker(t)

            if is_option:
                total_premium = finance.calculate_option_premium(
                    entry_price=entry_price,
                    qty=qty,
                    fees=fees,
                )
                finance.add_transaction(
                    date=form.get("trade_date", ""),
                    type=finance.TransactionType.PREMIUM,
                    amount=total_premium,
                    description=f"Prêmio {ticker} ({qty}x)",
                    position_id=pos_id,
                    is_simulated=is_simulated,
                )

                if form.get("reserve_darf") == "1":
                    trade_type = (form.get("trade_type") or "swing").strip().lower()
                    darf_amount = finance.calculate_darf_provision(
                        premium_amount=total_premium,
                        trade_type=trade_type,
                    )
                    if darf_amount != 0.0:
                        aliquota_opts = finance.option_tax_rate(trade_type)
                        finance.add_transaction(
                            date=form.get("trade_date", ""),
                            type=finance.TransactionType.DARF,
                            amount=darf_amount,
                            description=f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                            position_id=pos_id,
                            is_simulated=is_simulated,
                        )

        return redirect(_safe_next_url(form.get("next")) or url_for("positions"))

    @app.post("/positions/register-premium/<int:position_id>")
    def register_position_premium(position_id: int):
        next_url = _safe_next_url(request.form.get("next")) or url_for("positions")
        pos = get_position(position_id)
        if not pos:
            return redirect(next_url)

        ticker = (pos.get("ticker") or "").strip()
        underlying = (pos.get("underlying") or "").strip()
        if not underlying:
            underlying = _lookup_underlying_from_snapshot(ticker) or ""
        if not ticker or not _is_option_ticker(ticker):
            return redirect(next_url)

        side = (pos.get("side") or "").strip().lower()
        if side != "short":
            return redirect(next_url)

        try:
            entry_price = float(pos.get("entry_price") or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if entry_price <= 0 or qty <= 0:
            return redirect(next_url)

        if finance.has_position_premium(position_id):
            return redirect(next_url)

        try:
            fees = float(pos.get("fees") or 0.0)
        except (TypeError, ValueError):
            fees = 0.0

        total_premium = finance.calculate_option_premium(
            entry_price=entry_price,
            qty=qty,
            fees=fees,
        )
        if total_premium <= 0:
            return redirect(next_url)

        trade_date = pos.get("trade_date") or datetime.date.today().isoformat()
        is_simulated = bool(pos.get("is_simulated") or 0)

        finance.add_transaction(
            date=trade_date,
            type=finance.TransactionType.PREMIUM,
            amount=total_premium,
            description=f"Prêmio {ticker} ({qty}x)",
            position_id=position_id,
            is_simulated=is_simulated,
        )

        reserve_darf = request.form.get("reserve_darf", "1") == "1"
        if reserve_darf:
            trade_type = (pos.get("trade_type") or "swing").strip().lower()
            darf_amount = finance.calculate_darf_provision(
                premium_amount=total_premium,
                trade_type=trade_type,
            )
            if darf_amount != 0.0:
                aliquota_opts = finance.option_tax_rate(trade_type)
                finance.add_transaction(
                    date=trade_date,
                    type=finance.TransactionType.DARF,
                    amount=darf_amount,
                    description=f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                    position_id=position_id,
                    is_simulated=is_simulated,
                )

        return redirect(next_url)

    @app.post("/positions/recalc-premium/<int:position_id>")
    def recalc_position_premium(position_id: int):
        next_url = _safe_next_url(request.form.get("next")) or url_for("positions")
        pos = get_position(position_id)
        if not pos:
            return redirect(next_url)

        ticker = (pos.get("ticker") or "").strip()
        if not ticker or not _is_option_ticker(ticker):
            return redirect(next_url)

        side = (pos.get("side") or "").strip().lower()
        if side != "short":
            return redirect(next_url)

        try:
            entry_price = float(pos.get("entry_price") or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            fees = float(pos.get("fees") or 0.0)
        except (TypeError, ValueError):
            fees = 0.0

        if entry_price <= 0 or qty <= 0:
            return redirect(next_url)

        total_premium = finance.calculate_option_premium(
            entry_price=entry_price,
            qty=qty,
            fees=fees,
        )
        trade_date = pos.get("trade_date") or datetime.date.today().isoformat()
        trade_type = (pos.get("trade_type") or "swing").strip().lower()
        is_simulated = bool(pos.get("is_simulated") or 0)

        finance.recalc_position_premium_and_darf(
            position_id=position_id,
            trade_date=trade_date,
            ticker=ticker,
            qty=qty,
            premium_amount=total_premium,
            trade_type=trade_type,
            is_simulated=is_simulated,
        )
        return redirect(next_url)

    @app.post("/positions/update/<int:position_id>")
    def update_position_view(position_id: int):
        form = request.form
        status = form.get("status") or None
        ticker = (form.get("ticker") or "").strip()
        side_raw = form.get("side") or None
        strategy_tag_raw = form.get("strategy_tag") or None
        side_raw = _normalize_form_side(
            ticker=ticker,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
        )
        underlying = _resolve_underlying_for_position(
            ticker=ticker,
            underlying=form.get("underlying") or "",
            side=side_raw,
            strategy_tag=strategy_tag_raw,
        )
        is_simulated = None
        if form.get("is_simulated") is not None:
            is_simulated = form.get("is_simulated") == "1"
        parent_id = None
        if form.get("parent_position_id"):
            try:
                parent_id = int(form.get("parent_position_id"))
            except ValueError:
                parent_id = None
        update_position(
            position_id=position_id,
            ticker=ticker or None,
            underlying=underlying,
            trade_date=form.get("trade_date") or None,
            qty=int(form["qty"]) if form.get("qty") else None,
            entry_price=(
                _parse_form_float(form.get("entry_price"))
                if form.get("entry_price")
                else None
            ),
            fees=_parse_form_float(form.get("fees")) if form.get("fees") else None,
            status=status,
            exit_date=form.get("exit_date") or None,
            exit_price=(
                _parse_form_float(form.get("exit_price"))
                if form.get("exit_price")
                else None
            ),
            notes=form.get("notes") or None,
            trade_type=form.get("trade_type") or None,
            side=side_raw,
            irrf=_parse_form_float(form.get("irrf")) if form.get("irrf") else None,
            partial_date=form.get("partial_date") or None,
            partial_price=(
                _parse_form_float(form.get("partial_price"))
                if form.get("partial_price")
                else None
            ),
            partial_qty=int(form["partial_qty"]) if form.get("partial_qty") else None,
            exit_reason=form.get("exit_reason") or None,
            is_simulated=is_simulated,
            parent_position_id=parent_id,
            strategy_tag=strategy_tag_raw,
        )
        finance.sync_position_closure_effects(position_id=position_id)
        return redirect(_safe_next_url(form.get("next")) or url_for("positions"))

    @app.post("/positions/delete/<int:position_id>")
    def delete_position_view(position_id: int):
        delete_position(position_id=position_id)
        return redirect(
            _safe_next_url(request.form.get("next")) or url_for("positions")
        )

    def _parse_form_float(value: str | None) -> float:
        if not value:
            return 0.0
        text = value.strip().replace("%", "").replace(",", ".")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _parse_form_date(value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        # Aceita ISO (YYYY-MM-DD)
        try:
            return datetime.date.fromisoformat(text).isoformat()
        except ValueError:
            pass
        # Aceita dd/mm/YYYY (vencimento da B3 no snapshot)
        try:
            return datetime.datetime.strptime(text, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None

    def _lookup_underlying_from_snapshot(ticker: str) -> str | None:
        if not ticker:
            return None
        t = ticker.strip().upper()
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT underlying FROM option_snapshots WHERE ticker = %s ORDER BY snapshot_date DESC LIMIT 1",
                (t,),
            ).fetchone()
            if not row:
                return None
            return row.get("underlying") if isinstance(row, dict) else row[0]
        finally:
            conn.close()

    def _safe_next_url(value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        if not candidate.startswith("/positions"):
            return None
        return candidate

    def _is_option_ticker(ticker: str | None) -> bool:
        return infer_option_type(ticker or "") in {"CALL", "PUT"}

    def _normalize_form_side(
        *,
        ticker: str | None,
        side: str | None,
        strategy_tag: str | None,
        record_premium: bool = False,
    ) -> str:
        side_norm = (side or "").strip().lower()
        if side_norm in {"short", "vendida", "vendido", "v"}:
            return "short"
        strategy_norm = (strategy_tag or "").strip().lower()
        if record_premium:
            return "short"
        if strategy_norm in {"cash_put", "covered_call"} and _is_option_ticker(ticker):
            return "short"
        return "long"

    def _looks_like_equity_ticker(ticker: str | None) -> bool:
        text = (ticker or "").strip().upper()
        if not text:
            return False
        return re.fullmatch(r"[A-Z]{4}\d{1,2}", text) is not None

    def _resolve_underlying_for_position(
        *,
        ticker: str | None,
        underlying: str | None,
        side: str | None = None,
        strategy_tag: str | None = None,
    ) -> str:
        t = (ticker or "").strip().upper()
        u = (underlying or "").strip().upper()
        if u:
            return u

        snap_underlying = _lookup_underlying_from_snapshot(t)
        if snap_underlying:
            return snap_underlying.strip().upper()

        side_norm = (side or "").strip().lower()
        strat_norm = (strategy_tag or "").strip().lower()
        # Fallback para ações em estoque: quando o usuário não informar "Ativo",
        # usamos o próprio ticker da ação.
        if (
            t
            and _looks_like_equity_ticker(t)
            and side_norm != "short"
            and strat_norm not in {"cash_put", "covered_call", "ranking"}
        ):
            return t
        return u

    def _lookup_option_strike(ticker: str) -> float | None:
        """Recupera o strike do ticker de opção a partir do último snapshot."""

        if not ticker:
            return None
        t = ticker.strip().upper()
        conn = open_db()
        try:
            row = conn.execute(
                """
                SELECT strike
                FROM option_snapshots
                WHERE ticker = %s
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (t,),
            ).fetchone()
            if not row:
                return None
            strike = row.get("strike") if isinstance(row, dict) else row[0]
            return float(parse_ptbr_number(strike) or 0.0)
        finally:
            conn.close()

    def _auto_fees(
        *,
        ticker: str,
        underlying: str,
        qty: int,
        entry_price: float,
    ) -> float:
        """Calcula taxas padrão a partir das configurações, se possível."""

        fees_cfg: FeeSettings = get_fee_settings()
        t = (ticker or "").strip().upper()
        u = (underlying or "").strip().upper()
        qty = max(int(qty or 0), 0)
        entry_price = float(entry_price or 0.0)

        if not t or qty <= 0 or entry_price <= 0:
            return 0.0

        # Se ticker == underlying, tratamos como ação/ETF.
        if u and t == u:
            value = entry_price * qty
            return max(
                0.0,
                float(fees_cfg.equity_fixed)
                + (float(fees_cfg.equity_percent) / 100.0) * value,
            )

        # Caso contrário, usamos regra de opções.
        strike = _lookup_option_strike(t)
        if not strike or strike <= 0:
            # Sem strike conhecido, pelo menos aplicamos a parte fixa.
            return max(0.0, float(fees_cfg.option_fixed))
        # Interpretação: qty = número de opções (mesmo número de ações expostas).
        # Valor nocional aproximado = strike * qty.
        notional = strike * qty
        return max(
            0.0,
            float(fees_cfg.option_fixed)
            + (float(fees_cfg.option_percent_notional) / 100.0) * notional,
        )

    return app


if __name__ == "__main__":
    load_dotenv_once()
    app = create_app()
    debug_mode = os.getenv("OPCOES_WEB_DEBUG", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "sim",
    }
    app.run(debug=debug_mode)
