import argparse
import asyncio
import datetime as dt
import getpass
import os
import re
from pathlib import Path
from typing import List, Optional

from .auth import (
    create_user,
    get_user_app_schema,
    issue_temporary_password,
    list_user_schema_mappings,
    list_users,
    migrate_user_app_schemas,
    normalize_username,
)
from .scraper.run import scrape_all
from .enrich import enrich_csv
from .portfolio import add_position, list_positions, close_position
from .report import generate_report
from .snapshot_export import export_snapshot
from .tax import compute_tax
from .backfill_yfinance import backfill_prices
from .db_health import is_postgres_ready, run_db_check
from .db_health import resolve_postgres_target
from .db_migrate import clone_postgres_schema, migrate_postgres
from .db_optimize import optimize_postgres_schema
from . import finance
from .fundamentus import (
    FundamentusFilterConfig,
    FundamentusSchemaError,
    apply_filters,
    list_quarantined_snapshots,
    latest_snapshot_date,
    quarantine_snapshots,
    scrape_and_store,
)
from .history import (
    cleanup_history,
    list_decisions,
    record_decision,
    record_ranking_entries,
)
from .retention import (
    RetentionPolicy,
    apply_retention,
)
from .service_runs import (
    DEFAULT_SERVICE_KEY,
    fail_latest_running_service_run,
    finish_service_run,
    list_service_runs,
    start_service_run,
)
from .runtime_env import load_dotenv_once
from .exercise_fee_repair import (
    ExerciseFeeRepairError,
    repair_covered_call_exercise_sale_fee,
)
from .config import reset_pg_schema_override, set_pg_schema_override
from .ranking_page_cache import (
    build_cache_key as build_ranking_page_cache_key,
    set_cached_context as set_ranking_page_cache,
)
from .strategies import get_ranking_context


USER_BOOTSTRAP_MARKET_TABLES = [
    "settings",
    "option_snapshots",
    "underlying_snapshots",
    "flow_history",
    "iv_history",
    "ranking_runs",
    "ranking_entries",
    "fundamentus_runs",
    "fundamentus_snapshots",
    "fundamentus_filter_runs",
    "fundamentus_signals",
    "fundamentus_snapshot_integrity",
    "ticker_metadata",
]


def _bootstrap_user_schema(
    *,
    source_schema: str,
    target_schema: str,
    mode: str,
) -> None:
    target_target, target_errors = resolve_postgres_target()
    if target_target is None:
        details = "; ".join(target_errors) if target_errors else "configuração ausente"
        raise SystemExit(
            f"Falha ao resolver PostgreSQL para bootstrap do usuário: {details}"
        )

    include_tables = None
    if mode == "market":
        include_tables = USER_BOOTSTRAP_MARKET_TABLES

    print(f"Bootstrap do schema {target_schema} a partir de {source_schema}...")
    print(
        "Modo: "
        + (
            "base de mercado/configuração sem copiar posições do outro usuário"
            if mode == "market"
            else "cópia integral do schema operacional de origem"
        )
    )
    try:
        report = clone_postgres_schema(
            dsn=target_target.dsn,
            source_schema=source_schema,
            target_schema=target_schema,
            include_tables=include_tables,
            truncate_target=True,
        )
    except Exception as exc:
        raise SystemExit(f"Falha no bootstrap do usuário: {exc}") from exc

    for item in report.get("tables", []):
        print(
            f"  - {item['source_schema']}.{item['table']} -> "
            f"{item['target_schema']}.{item['table']} ({item['rows']} linhas)"
        )
    print(f"Total de linhas copiadas: {report.get('total_rows', 0)}")
    print(
        "Bootstrap concluído. O novo usuário já pode entrar sem herdar operações pessoais do schema base."
        if mode == "market"
        else "Bootstrap concluído com cópia integral do schema operacional."
    )


def sanitize_schema_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "public"
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def _resolve_user_target_schema(
    *,
    username: str,
    explicit_schema: str | None = None,
) -> str:
    if explicit_schema:
        return sanitize_schema_name(explicit_schema)
    mapped = get_user_app_schema(username, fail_on_collision=False)
    if mapped:
        return mapped
    return sanitize_schema_name(username)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="opcoes",
        description="Coletor diário de opções (CALLs/PUTs) do opcoes.net.br",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scrape", help="Executa a coleta")
    sc.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Lista de papéis separados por vírgula (ex.: ABEV3,BBAS3). Padrão: todos.",
    )
    sc.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Limita a quantidade de papéis processados (para testes).",
    )
    sc.add_argument(
        "--output",
        type=Path,
        default=Path("data/opcoes_latest.csv"),
        help="Arquivo CSV de saída (default: data/opcoes_latest.csv)",
    )
    sc.add_argument(
        "--headful",
        action="store_true",
        help="Abre o navegador visível (debug).",
    )
    sc.add_argument(
        "--throttle",
        type=float,
        default=1.0,
        help="Atraso (segundos) entre ações para simular ritmo humano.",
    )
    sc.add_argument(
        "--goto-timeout",
        type=int,
        default=60000,
        help="Timeout do page.goto em milissegundos (default: 60000).",
    )
    sc.add_argument(
        "--proxy-server",
        type=str,
        default=None,
        help="Proxy HTTP/HTTPS, ex.: http://host:3128 ou socks5://host:1080",
    )
    sc.add_argument(
        "--proxy-username",
        type=str,
        default=None,
        help="Usuário para autenticação no proxy (opcional).",
    )
    sc.add_argument(
        "--proxy-password",
        type=str,
        default=None,
        help="Senha para autenticação no proxy (opcional).",
    )
    sc.add_argument(
        "--fundamentals",
        type=Path,
        default=None,
        help=(
            "CSV opcional com fundamentos por ticker para calcular earnings_yield/PE. "
            "Colunas aceitas: ticker e (earnings_yield_ttm | pe_ttm | lpa_ttm + preco | "
            "lucro_liquido_ttm + acoes_total + preco)."
        ),
    )
    sc.add_argument(
        "--statusinvest",
        action="store_true",
        help=(
            "Obtém P/L e E/P automaticamente do Status Invest para os papéis processados. "
            "Equivale a fornecer fundamentos externos, porém baixados online."
        ),
    )
    sc.add_argument(
        "--backfill-days",
        type=int,
        default=120,
        help="Após o scrape, baixa histórico de preços dos underlyings via yfinance (default: 120 dias). Use 0 para não baixar.",
    )
    sc.add_argument(
        "--no-backfill",
        action="store_true",
        help="Não roda o backfill de preços após o scrape.",
    )
    sc.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Desativa o uso de checkpoint incremental (habilitado por padrão).",
    )
    sc.set_defaults(resume=True)
    sc.add_argument(
        "--resume-file",
        type=Path,
        default=None,
        help="Arquivo de checkpoint da retomada (default: <output>.checkpoint.json).",
    )

    ec = sub.add_parser("enrich", help="Enriquece um CSV existente com E/P e P/L")
    ec.add_argument(
        "--input",
        type=Path,
        default=Path("data/opcoes_latest.csv"),
        help="Arquivo CSV de entrada a enriquecer (default: data/opcoes_latest.csv)",
    )
    ec.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Arquivo CSV de saída (default: sobrescreve o de entrada)",
    )
    ec.add_argument(
        "--fundamentals",
        type=Path,
        default=None,
        help=(
            "CSV opcional com fundamentos (ticker + earnings_yield_ttm | pe_ttm | lpa_ttm + preco | "
            "lucro_liquido_ttm + acoes_total + preco). Se não informado, pode usar --statusinvest."
        ),
    )
    ec.add_argument(
        "--statusinvest",
        action="store_true",
        help=(
            "Baixa P/L do Status Invest e calcula E/P. Se usado, ignora --fundamentals."
        ),
    )
    ec.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout por requisição ao Status Invest (s).",
    )
    ec.add_argument(
        "--throttle",
        type=float,
        default=0.8,
        help="Atraso entre requisições ao Status Invest (s).",
    )
    ec.add_argument(
        "--only-units",
        action="store_true",
        help="Ao usar Status Invest, preencher apenas para Units (ignora demais).",
    )

    pc = sub.add_parser("position", help="Gerencia posições compradas/vendidas")
    pcs = pc.add_subparsers(dest="subcmd", required=True)

    pa = pcs.add_parser("add", help="Registra uma nova posição (compra/venda)")
    pa.add_argument("--ticker", required=True, help="Ticker da opção (ex.: USIMJ605)")
    pa.add_argument(
        "--underlying", required=True, help="Ticker do ativo base (ex.: USIM5)"
    )
    pa.add_argument("--trade-date", required=True, help="Data da compra (YYYY-MM-DD)")
    pa.add_argument("--qty", type=int, required=True, help="Quantidade de contratos")
    pa.add_argument("--price", type=float, required=True, help="Preço por contrato")
    pa.add_argument(
        "--fees", type=float, default=0.0, help="Custos/Taxas adicionais (opcional)"
    )
    pa.add_argument(
        "--side",
        choices=["long", "short"],
        default="long",
        help="Direção da posição: long (comprada) ou short (vendida).",
    )
    pa.add_argument("--notes", default=None, help="Observações (opcional)")
    pa.add_argument(
        "--parent-id",
        type=int,
        default=None,
        help="ID da posição de underlying associada (lote pai, opcional).",
    )
    pa.add_argument(
        "--simulated",
        action="store_true",
        help="Marca a posição como aporte simulado/fictício (não real).",
    )

    pl = pcs.add_parser("list", help="Lista posições registradas")
    group = pl.add_mutually_exclusive_group()
    group.add_argument(
        "--include-closed", action="store_true", help="Inclui posições fechadas"
    )
    group.add_argument(
        "--only-closed", action="store_true", help="Mostra apenas fechadas"
    )
    pl.add_argument("--ticker", type=str, default=None, help="Filtra por ticker exato")

    pc_close = pcs.add_parser("close", help="Fecha uma posição aberta")
    pc_close.add_argument(
        "--id", type=int, required=True, help="ID da posição (veja em position list)"
    )
    pc_close.add_argument(
        "--exit-date", required=True, help="Data de saída (YYYY-MM-DD)"
    )
    pc_close.add_argument(
        "--price", type=float, required=True, help="Preço de saída por contrato"
    )

    rc = sub.add_parser("report", help="Gera relatório diário pós-scrape")
    rc.add_argument(
        "--min-score",
        type=int,
        default=8,
        help="Score mínimo para oportunidades (default: 8)",
    )
    rc.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Quantidade máxima de oportunidades listadas",
    )
    rc.add_argument(
        "--no-persist",
        dest="persist",
        action="store_false",
        help="Não gravar histórico de ranking no banco (default: persiste).",
    )

    rank_cache = sub.add_parser(
        "ranking-cache",
        help="Aquece ou atualiza o cache persistido da home de ranking.",
    )
    rank_cache_sub = rank_cache.add_subparsers(dest="subcmd", required=True)
    rank_cache_refresh = rank_cache_sub.add_parser(
        "refresh",
        help="Recalcula e persiste o contexto padrão da home de ranking.",
    )
    rank_cache_refresh.add_argument(
        "--username",
        default=None,
        help="Usuário para aquecer o cache no schema/namespace dele.",
    )

    sn = sub.add_parser("snapshot", help="Opera sobre snapshots diários")
    sns = sn.add_subparsers(dest="subcmd", required=True)
    se = sns.add_parser("export", help="Exporta snapshot para CSV")
    se.add_argument(
        "--date",
        type=str,
        default=None,
        help="Data do snapshot (YYYY-MM-DD). Default: última disponível.",
    )
    se.add_argument(
        "--output",
        type=Path,
        default=Path("data/opcoes_latest.csv"),
        help="Arquivo CSV de saída (default: data/opcoes_latest.csv)",
    )

    dec = sub.add_parser(
        "decision", help="Registra ou lista decisões (linha completa do snapshot)"
    )
    decs = dec.add_subparsers(dest="subcmd", required=True)
    dec_add = decs.add_parser(
        "add",
        help="Registra a linha do ticker do snapshot mais recente (ou data específica)",
    )
    dec_add.add_argument(
        "--ticker", required=True, help="Ticker da opção (ex.: B3SAB150)"
    )
    dec_add.add_argument(
        "--snapshot-date",
        type=str,
        default=None,
        help="Data do snapshot YYYY-MM-DD (opcional)",
    )
    dec_add.add_argument(
        "--notes", type=str, default=None, help="Observações (opcional)"
    )
    dec_list = decs.add_parser("list", help="Lista decisões registradas")
    dec_list.add_argument(
        "--limit", type=int, default=50, help="Limite de linhas (default: 50)"
    )

    cl = sub.add_parser(
        "cleanup", help="Remove rankings (e opcionalmente snapshots) antigos/vencidos"
    )
    cl.add_argument(
        "--retention-days",
        type=int,
        default=180,
        help="Janela de retenção em dias (default: 180)",
    )
    cl.add_argument(
        "--purge-snapshots",
        action="store_true",
        help="Também remove option/underlying snapshots antigos e vencidos (cautela!).",
    )

    tc = sub.add_parser("tax", help="Relatório fiscal (DARF)")
    rt = sub.add_parser(
        "retention",
        help="Aplica retencao automatica dos dados de mercado, preservando dados do usuario e fiscais.",
    )
    rt.add_argument(
        "--option-days",
        type=int,
        default=120,
        help="Dias de retencao dos option_snapshots (default: 120).",
    )
    rt.add_argument(
        "--option-expired-grace-days",
        type=int,
        default=30,
        help="Dias de graca apos o vencimento para option_snapshots recentes (default: 30).",
    )
    rt.add_argument(
        "--underlying-days",
        type=int,
        default=400,
        help="Dias de retencao dos underlying_snapshots para suportar HV longa (default: 400).",
    )
    rt.add_argument(
        "--iv-days",
        type=int,
        default=240,
        help="Dias de retencao do iv_history (default: 240).",
    )
    rt.add_argument(
        "--iv-expired-grace-days",
        type=int,
        default=30,
        help="Dias de graca apos o vencimento para iv_history recente (default: 30).",
    )
    rt.add_argument(
        "--flow-days",
        type=int,
        default=60,
        help="Dias de retencao do flow_history (default: 60).",
    )
    rt.add_argument(
        "--ranking-days",
        type=int,
        default=60,
        help="Dias de retencao de ranking_entries/ranking_runs (default: 60).",
    )
    rt.add_argument(
        "--fundamentus-days",
        type=int,
        default=365,
        help="Dias de retencao das tabelas Fundamentus (default: 365).",
    )
    rt.add_argument(
        "--today",
        type=str,
        default=None,
        help="Data de referencia YYYY-MM-DD para simulacao/teste.",
    )
    rt.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra quanto seria removido sem apagar nada.",
    )

    tc.add_argument("--year", type=int, required=True, help="Ano (YYYY)")
    tc.add_argument("--month", type=int, required=True, help="Mês (1-12)")
    tc.add_argument(
        "--mode",
        choices=["real", "simulated", "all"],
        default="real",
        help="Filtra posições reais, simuladas, ou ambas (default: real).",
    )

    uc = sub.add_parser("user", help="Gerencia usuários para acesso web")
    ucs = uc.add_subparsers(dest="subcmd", required=True)

    uc_create = ucs.add_parser("create", help="Cria usuário de acesso web")
    uc_create.add_argument(
        "--username", required=True, help="Nome do usuário (minúsculo, 3-64 chars)"
    )
    uc_create.add_argument(
        "--password",
        default=None,
        help="Senha. Se omitida, solicita via prompt seguro.",
    )
    uc_create.add_argument(
        "--replace",
        action="store_true",
        help="Se o usuário já existir, atualiza a senha.",
    )

    uc_list = ucs.add_parser("list", help="Lista usuários de acesso web")
    uc_list.add_argument(
        "--all",
        action="store_true",
        help="Inclui usuários inativos.",
    )

    uc_invite = ucs.add_parser(
        "invite",
        help="Cria ou renova um usuário com senha temporária de primeiro acesso.",
    )
    uc_invite.add_argument(
        "--username", required=True, help="Nome do usuário (minúsculo, 3-64 chars)"
    )
    uc_invite.add_argument(
        "--replace",
        action="store_true",
        help="Se o usuário já existir, emite nova senha temporária.",
    )
    uc_invite.add_argument(
        "--bootstrap",
        action="store_true",
        help="Também prepara o schema inicial do usuário a partir de um schema base.",
    )
    uc_invite.add_argument(
        "--from-schema",
        default="admin",
        help="Schema base de onde copiar a estrutura inicial (default: admin).",
    )
    uc_invite.add_argument(
        "--target-schema",
        default=None,
        help="Schema de destino no PostgreSQL (default: schema exclusivo atribuído ao usuário).",
    )
    uc_invite.add_argument(
        "--mode",
        choices=["market", "full"],
        default="market",
        help=(
            "market copia apenas base de mercado/configuração; "
            "full copia também posições e histórico fiscal do schema base."
        ),
    )

    uc_bootstrap = ucs.add_parser(
        "bootstrap",
        help="Cria usuário web e prepara o schema inicial a partir de um schema base.",
    )
    uc_bootstrap.add_argument(
        "--username", required=True, help="Nome do usuário (minúsculo, 3-64 chars)"
    )
    uc_bootstrap.add_argument(
        "--password",
        default=None,
        help="Senha. Se omitida, solicita via prompt seguro.",
    )
    uc_bootstrap.add_argument(
        "--replace",
        action="store_true",
        help="Se o usuário já existir, atualiza a senha.",
    )
    uc_bootstrap.add_argument(
        "--from-schema",
        default="admin",
        help="Schema base de onde copiar a estrutura inicial (default: admin).",
    )
    uc_bootstrap.add_argument(
        "--target-schema",
        default=None,
        help="Schema de destino no PostgreSQL (default: schema exclusivo atribuído ao usuário).",
    )
    uc_bootstrap.add_argument(
        "--mode",
        choices=["market", "full"],
        default="market",
        help=(
            "market copia apenas base de mercado/configuração; "
            "full copia também posições e histórico fiscal do schema base."
        ),
    )

    uc_schema_audit = ucs.add_parser(
        "audit-schemas",
        help="Lista o mapeamento username -> app_schema e identifica migrações pendentes.",
    )
    uc_schema_audit.add_argument(
        "--pending-only",
        action="store_true",
        help="Mostra apenas usuários que ainda precisam gravar ou revisar app_schema.",
    )

    uc_schema_migrate = ucs.add_parser(
        "migrate-schemas",
        help="Atribui app_schema exclusivo aos usuários e replica schemas legados colididos quando necessário.",
    )
    uc_schema_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o plano sem gravar alterações nem clonar schemas.",
    )
    uc_schema_migrate.add_argument(
        "--no-clone-legacy",
        action="store_true",
        help="Não replica o schema legado para usuários que receberem schema novo.",
    )

    src = sub.add_parser(
        "service-run", help="Registra e consulta execucoes dos servicos agendados"
    )
    srcs = src.add_subparsers(dest="subcmd", required=True)

    sr_start = srcs.add_parser("start", help="Marca o inicio de uma execucao")
    sr_start.add_argument(
        "--service",
        default=DEFAULT_SERVICE_KEY,
        help=f"Chave do servico (default: {DEFAULT_SERVICE_KEY}).",
    )
    sr_start.add_argument(
        "--trigger",
        default="systemd",
        help="Origem do disparo (ex.: systemd, manual).",
    )
    sr_start.add_argument(
        "--summary",
        default=None,
        help="Resumo opcional para aparecer no painel.",
    )
    sr_start.add_argument(
        "--step",
        default="starting",
        help="Etapa inicial da execucao (default: starting).",
    )
    sr_start.add_argument(
        "--scheduled-for",
        default=None,
        help="Horario previsto em ISO 8601 (opcional).",
    )

    sr_finish = srcs.add_parser("finish", help="Marca o termino de uma execucao")
    sr_finish.add_argument("--run-id", required=True, help="ID retornado no start.")
    sr_finish.add_argument(
        "--status",
        required=True,
        choices=["success", "failed"],
        help="Resultado final da execucao.",
    )
    sr_finish.add_argument(
        "--summary",
        default=None,
        help="Resumo final mostrado no painel.",
    )
    sr_finish.add_argument(
        "--message",
        default=None,
        help="Detalhe do erro ou observacao final.",
    )
    sr_finish.add_argument(
        "--step",
        default="finished",
        help="Etapa final registrada no painel.",
    )

    sr_list = srcs.add_parser("list", help="Lista execucoes recentes")
    sr_list.add_argument(
        "--service",
        default=None,
        help="Filtra por chave de servico.",
    )
    sr_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Quantidade maxima de linhas (default: 20).",
    )

    sr_watchdog = srcs.add_parser(
        "watchdog",
        help="Marca como falha a ultima execucao running quando o monitor externo detectar interrupcao.",
    )
    sr_watchdog.add_argument(
        "--service",
        default=DEFAULT_SERVICE_KEY,
        help=f"Chave do servico (default: {DEFAULT_SERVICE_KEY}).",
    )
    sr_watchdog.add_argument(
        "--summary",
        default="Watchdog marcou a execucao como interrompida.",
        help="Resumo final mostrado no painel.",
    )
    sr_watchdog.add_argument(
        "--message",
        default=(
            "O monitor externo detectou que o servico nao esta mais ativo, "
            "mas o painel ainda mostrava a execucao em andamento."
        ),
        help="Mensagem final exibida como detalhe do erro.",
    )
    sr_watchdog.add_argument(
        "--step",
        default="watchdog",
        help="Etapa final registrada no painel.",
    )

    dbc = sub.add_parser("db", help="Diagnóstico de banco de dados")
    dbs = dbc.add_subparsers(dest="subcmd", required=True)
    db_check = dbs.add_parser(
        "check", help="Valida configuração e conexão com PostgreSQL"
    )
    db_check.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout em segundos para teste de rede/SQL (default: 5).",
    )
    db_optimize = dbs.add_parser(
        "optimize",
        help="Cria índices recomendados no schema PostgreSQL para reduzir latência de runtime.",
    )
    db_optimize.add_argument(
        "--username",
        type=str,
        default="admin",
        help="Usuário de referência para derivar schema default (default: admin).",
    )
    db_optimize.add_argument(
        "--schema",
        type=str,
        default=None,
        help="Schema de destino no PostgreSQL (default: username normalizado).",
    )
    db_optimize.add_argument(
        "--no-analyze",
        action="store_true",
        help="Não executa ANALYZE após criar índices.",
    )
    db_migrate = dbs.add_parser(
        "migrate",
        help="Migra todas as tabelas dos schemas da aplicação entre dois PostgreSQLs via COPY streaming.",
    )
    db_migrate.add_argument(
        "--target-dsn",
        type=str,
        required=True,
        help="DSN PostgreSQL de destino. Ex.: postgresql://user:senha@127.0.0.1:15432/mercado_opcoes",
    )
    db_migrate.add_argument(
        "--source-dsn",
        type=str,
        default=None,
        help="DSN PostgreSQL de origem. Se omitido, usa o .env local carregado pela aplicação.",
    )
    db_migrate.add_argument(
        "--source-app-schema",
        type=str,
        default="admin",
        help="Schema operacional de origem (default: admin).",
    )
    db_migrate.add_argument(
        "--target-app-schema",
        type=str,
        default="admin",
        help="Schema operacional de destino (default: admin).",
    )
    db_migrate.add_argument(
        "--source-auth-schema",
        type=str,
        default="auth",
        help="Schema de autenticação de origem (default: auth).",
    )
    db_migrate.add_argument(
        "--target-auth-schema",
        type=str,
        default="auth",
        help="Schema de autenticação de destino (default: auth).",
    )
    db_migrate.add_argument(
        "--no-truncate",
        action="store_true",
        help="Não limpa as tabelas de destino antes da cópia. Use apenas em cenários muito controlados.",
    )

    fc = sub.add_parser("fundamentus", help="Coleta Fundamentus (busca avançada)")
    fc.add_argument(
        "--pl-min", type=float, default=0.0, help="Filtro mínimo de P/L (default: 0)"
    )
    fc.add_argument(
        "--patrim-min",
        type=float,
        default=0.0,
        help="Filtro mínimo de Patrimônio Líquido (default: 0)",
    )
    fc.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout da requisição ao Fundamentus (s).",
    )
    fc.add_argument(
        "--snapshot-date",
        type=str,
        default=None,
        help="Data do snapshot (YYYY-MM-DD). Default: hoje.",
    )

    default_cfg = FundamentusFilterConfig()
    ff = sub.add_parser(
        "fundamentus-filter", help="Aplica filtros Fundamentus no snapshot"
    )
    ff.add_argument(
        "--snapshot-date",
        type=str,
        default=None,
        help="Data do snapshot (YYYY-MM-DD). Default: última disponível.",
    )
    ff.add_argument(
        "--liq-2m-min",
        type=float,
        default=default_cfg.liq_2m_min,
        help="Liquidez 2m mínima (default: 1.000.000).",
    )
    ff.add_argument(
        "--div-bruta-patrim-max",
        type=float,
        default=default_cfg.div_bruta_patrim_max,
        help="Dívida/Patrimônio máximo (default: 2).",
    )
    ff.add_argument(
        "--cresc-rec-5a-min",
        type=float,
        default=default_cfg.cresc_rec_5a_min,
        help="Cresc. Rec. 5a mínimo (default: 0).",
    )
    ff.add_argument(
        "--div-yield-min",
        type=float,
        default=default_cfg.div_yield_min,
        help="Dividend Yield mínimo (default: 6).",
    )
    ff.add_argument(
        "--roe-min",
        type=float,
        default=default_cfg.roe_min,
        help="ROE mínimo (default: 15).",
    )
    ff.add_argument(
        "--margem-liquida-min",
        type=float,
        default=default_cfg.margem_liquida_min,
        help="Margem Líquida mínima (default: 10).",
    )
    ff.add_argument(
        "--no-margem-liquida-zero",
        action="store_true",
        help="Desativa a exceção de margem líquida igual a 0%.",
    )

    integrity = sub.add_parser(
        "fundamentus-integrity",
        help="Lista ou coloca em quarentena snapshots Fundamentus inválidos.",
    )
    integrity_actions = integrity.add_subparsers(
        dest="fundamentus_integrity_action",
        required=True,
    )
    integrity_actions.add_parser("list", help="Lista snapshots em quarentena.")
    quarantine = integrity_actions.add_parser(
        "quarantine",
        help="Preserva snapshots inválidos, excluindo-os da estratégia.",
    )
    quarantine.add_argument(
        "--from-date", required=True, help="Data inicial YYYY-MM-DD."
    )
    quarantine.add_argument("--to-date", required=True, help="Data final YYYY-MM-DD.")
    quarantine.add_argument(
        "--reason", required=True, help="Motivo auditável da quarentena."
    )

    repair = sub.add_parser(
        "repair",
        help="Corrige apenas inconsistencias historicas validadas pela auditoria.",
    )
    repairs = repair.add_subparsers(dest="subcmd", required=True)
    call_fee_repair = repairs.add_parser(
        "covered-call-exercise-fee",
        help="Simula ou corrige taxa de venda ausente em CALL exercida.",
    )
    call_fee_repair.add_argument(
        "--call-position-id", type=int, required=True, help="ID da CALL exercida."
    )
    call_fee_repair.add_argument(
        "--stock-position-id",
        type=int,
        required=True,
        help="ID do historico de acao fechado pelo exercicio.",
    )
    call_fee_repair.add_argument(
        "--sale-fees", type=float, required=True, help="Despesas da venda na nota."
    )
    call_fee_repair.add_argument(
        "--apply",
        action="store_true",
        help="Aplica a correcao depois de validar todos os vinculos. Sem esta flag, apenas simula.",
    )

    return parser.parse_args()


def main() -> None:
    loaded_env_path = load_dotenv_once()
    args = parse_args()

    if args.cmd == "scrape":
        symbols: Optional[List[str]] = None
        if args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

        proxy_settings = None
        if args.proxy_server:
            proxy_settings = {"server": args.proxy_server}
            if args.proxy_username:
                proxy_settings["username"] = args.proxy_username
            if args.proxy_password:
                proxy_settings["password"] = args.proxy_password

        # Interpreta alias: --fundamentals statusinvest
        use_status_invest = bool(args.statusinvest)
        if args.fundamentals and str(args.fundamentals).lower() == "statusinvest":
            use_status_invest = True
            args.fundamentals = None

        # Executa loop assíncrono do Playwright
        asyncio.run(
            scrape_all(
                symbols=symbols,
                output_csv=args.output,
                max_symbols=args.max_symbols,
                headless=not args.headful,
                throttle_sec=args.throttle,
                goto_timeout_ms=args.goto_timeout,
                proxy_settings=proxy_settings,
                fundamentals_csv=args.fundamentals,
                use_status_invest=use_status_invest,
                resume=bool(getattr(args, "resume", True)),
                progress_path=getattr(args, "resume_file", None),
            )
        )
        # Opcionalmente, roda backfill de preços para viabilizar HV/IV Rank
        if not args.no_backfill and args.backfill_days > 0:
            backfill_prices(days=args.backfill_days)
    elif args.cmd == "enrich":
        use_status_invest = bool(args.statusinvest)
        fundamentals_csv = args.fundamentals
        # Alias: --fundamentals statusinvest
        if fundamentals_csv and str(fundamentals_csv).lower() == "statusinvest":
            use_status_invest = True
            fundamentals_csv = None

        output = enrich_csv(
            input_csv=args.input,
            output_csv=args.output,
            use_status_invest=use_status_invest,
            fundamentals_csv=fundamentals_csv,
            timeout=args.timeout,
            throttle=args.throttle,
            only_units=bool(getattr(args, "only_units", False)),
        )
        print(f"CSV enriquecido em: {output}")
    elif args.cmd == "position":
        if args.subcmd == "add":
            trade_date = _parse_trade_date(args.trade_date)
            pos_id = add_position(
                ticker=args.ticker,
                underlying=args.underlying,
                trade_date=trade_date,
                qty=args.qty,
                entry_price=args.price,
                fees=args.fees,
                side=args.side,
                notes=args.notes,
                is_simulated=bool(getattr(args, "simulated", False)),
                parent_position_id=getattr(args, "parent_id", None),
            )
            print(f"Posição registrada com ID {pos_id}.")
        elif args.subcmd == "list":
            positions = list_positions(
                include_closed=args.include_closed,
                only_closed=args.only_closed,
                ticker=args.ticker,
            )
            if not positions:
                print("Nenhuma posição encontrada.")
            else:
                _print_positions(positions)
        elif args.subcmd == "close":
            exit_date = _parse_trade_date(args.exit_date)
            try:
                close_position(
                    position_id=args.id, exit_date=exit_date, exit_price=args.price
                )
                finance.sync_position_closure_effects(position_id=args.id)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"Posição {args.id} fechada em {exit_date} a {args.price:.2f}.")
    elif args.cmd == "report":
        data = generate_report(min_score=args.min_score, limit=args.limit)
        _print_report(data)
        if getattr(args, "persist", True):
            record_ranking_entries(
                data.snapshot_date,
                categories={
                    "top": data.opportunities,
                    "racional": data.rational_opportunities,
                    "loteria": data.lottery_opportunities,
                    "teorica": data.theoretical_opportunities,
                },
                params={"min_score": args.min_score, "limit": args.limit},
            )
    elif args.cmd == "ranking-cache":
        if args.subcmd == "refresh":
            normalized_username = normalize_username(args.username or "")
            namespace = "global"
            try:
                if normalized_username:
                    target_schema = get_user_app_schema(normalized_username)
                    if not target_schema:
                        raise SystemExit(
                            f"Usuário '{normalized_username}' não possui app_schema resolvido."
                        )
                    set_pg_schema_override(target_schema)
                    namespace = f"user:{normalized_username}"

                ctx = get_ranking_context({})
                ttl_raw = (os.getenv("OPCOES_RANKING_CACHE_SECONDS") or "45").strip()
                try:
                    ttl_seconds = max(int(ttl_raw), 0)
                except ValueError:
                    ttl_seconds = 45
                cache_key = build_ranking_page_cache_key(
                    route_name="index",
                    namespace=namespace,
                    args_signature=(),
                )
                set_ranking_page_cache(
                    cache_key=cache_key,
                    namespace=namespace,
                    route_name="index",
                    args_signature=(),
                    ctx=ctx,
                    ttl_seconds=ttl_seconds,
                )
                print(
                    f"Ranking cache atualizado: namespace={namespace} ttl={ttl_seconds}s"
                )
            finally:
                if normalized_username:
                    reset_pg_schema_override()
    elif args.cmd == "snapshot":
        if args.subcmd == "export":
            try:
                date = _parse_trade_date(args.date) if args.date else None
            except SystemExit:
                raise SystemExit(
                    "Data inválida em --date. Use o formato YYYY-MM-DD."
                ) from None
            try:
                out = export_snapshot(output_csv=args.output, snapshot_date=date)
            except RuntimeError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"Snapshot exportado para: {out}")
    elif args.cmd == "decision":
        if args.subcmd == "add":
            snap_date = None
            if args.snapshot_date:
                try:
                    snap_date = _parse_trade_date(args.snapshot_date)
                except SystemExit:
                    raise SystemExit(
                        "Data inválida em --snapshot-date. Use o formato YYYY-MM-DD."
                    ) from None
            decision_id = record_decision(
                args.ticker,
                snapshot_date=snap_date,
                notes=args.notes,
            )
            if decision_id is None:
                raise SystemExit(
                    f"Ticker {args.ticker} não encontrado no snapshot informado."
                )
            print(f"Decisão registrada com ID {decision_id}.")
        elif args.subcmd == "list":
            rows = list_decisions(limit=args.limit)
            if not rows:
                print("Nenhuma decisão registrada.")
            else:
                _print_decisions(rows)
    elif args.cmd == "cleanup":
        removed = cleanup_history(
            retention_days=args.retention_days, purge_snapshots=args.purge_snapshots
        )
        print(
            "Limpeza concluída: "
            f"rankings {removed['ranking_entries']} apagados, runs {removed['ranking_runs']} apagados, "
            f"snapshots {removed['option_snapshots']} apagados, underlyings {removed['underlying_snapshots']} apagados."
        )
    elif args.cmd == "retention":
        ref_today = _parse_trade_date(args.today) if args.today else None
        policy = RetentionPolicy(
            option_snapshot_days=args.option_days,
            option_expired_grace_days=args.option_expired_grace_days,
            underlying_snapshot_days=args.underlying_days,
            iv_history_days=args.iv_days,
            iv_expired_grace_days=args.iv_expired_grace_days,
            flow_history_days=args.flow_days,
            ranking_days=args.ranking_days,
            fundamentus_days=args.fundamentus_days,
        )
        report = apply_retention(
            policy=policy,
            today=dt.date.fromisoformat(ref_today) if ref_today else None,
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        action_label = (
            "Previa de retencao" if report["dry_run"] else "Retencao aplicada"
        )
        print(f"{action_label} em {report['today']}")
        print("Dados preservados para sempre:")
        for table in report["preserved_forever"]:
            print(f"  - {table}")
        print("Janela automatica de limpeza:")
        print(
            "  - option_snapshots: "
            f"{report['policy']['option_snapshot_days']} dias + "
            f"{report['policy']['option_expired_grace_days']} dias apos vencimento"
        )
        print(
            "  - underlying_snapshots: "
            f"{report['policy']['underlying_snapshot_days']} dias"
        )
        print(
            "  - iv_history: "
            f"{report['policy']['iv_history_days']} dias + "
            f"{report['policy']['iv_expired_grace_days']} dias apos vencimento"
        )
        print(f"  - flow_history: {report['policy']['flow_history_days']} dias")
        print(
            f"  - ranking_entries/ranking_runs: {report['policy']['ranking_days']} dias"
        )
        print(f"  - fundamentus_*: {report['policy']['fundamentus_days']} dias")
        removed = report["removed"]
        print("Resultado:")
        print(
            "  - option_snapshots: "
            f"{removed['option_snapshots']} "
            f"(idade={removed['option_snapshots_age']}, vencidos={removed['option_snapshots_expired']})"
        )
        print(f"  - underlying_snapshots: {removed['underlying_snapshots']}")
        print(
            "  - iv_history: "
            f"{removed['iv_history']} "
            f"(idade={removed['iv_history_age']}, vencidos={removed['iv_history_expired']})"
        )
        print(f"  - flow_history: {removed['flow_history']}")
        print(f"  - ranking_entries: {removed['ranking_entries']}")
        print(f"  - ranking_runs: {removed['ranking_runs']}")
        print(f"  - fundamentus_snapshots: {removed['fundamentus_snapshots']}")
        print(f"  - fundamentus_runs: {removed['fundamentus_runs']}")
        print(f"  - fundamentus_signals: {removed['fundamentus_signals']}")
        print(f"  - fundamentus_filter_runs: {removed['fundamentus_filter_runs']}")
        print(
            "  - fundamentus_snapshot_integrity: "
            f"{removed['fundamentus_snapshot_integrity']}"
        )
    elif args.cmd == "tax":
        mode = (args.mode or "real").strip().lower()
        is_simulated: Optional[bool]
        if mode == "simulated":
            is_simulated = True
        elif mode == "all":
            is_simulated = None
        else:
            mode = "real"
            is_simulated = False
        summary = compute_tax(
            month=args.month, year=args.year, is_simulated=is_simulated
        )
        print(f"Relatório fiscal {summary.month:02d}/{summary.year} (modo: {mode})")
        print(
            f"  Swing trade: lucro líquido R$ {summary.swing_net:.2f}, IR devido R$ {summary.swing_ir:.2f}, IRRF R$ {summary.swing_irrf:.2f}"
        )
        print(
            f"  Day trade:   lucro líquido R$ {summary.daytrade_net:.2f}, IR devido R$ {summary.daytrade_ir:.2f}, IRRF R$ {summary.daytrade_irrf:.2f}"
        )
        print(
            f"  Base tributÃ¡vel: swing R$ {summary.swing_taxable:.2f}, day trade R$ {summary.daytrade_taxable:.2f}"
        )
        print(
            f"  PrejuÃ­zo acumulado: swing R$ {summary.swing_loss_carry_out:.2f}, day trade R$ {summary.daytrade_loss_carry_out:.2f}"
        )
        print(
            f"  Total IR devido: R$ {summary.total_ir:.2f} (IRRF a compensar: R$ {summary.total_irrf:.2f})"
        )
        print(f"  DARF lÃ­quida do mÃªs: R$ {summary.net_ir_due:.2f}")
    elif args.cmd == "user":
        if args.subcmd == "create":
            password = args.password
            if not password:
                password = getpass.getpass("Senha do usuário: ")
            try:
                created = create_user(
                    username=args.username,
                    password=password,
                    replace=bool(getattr(args, "replace", False)),
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if created:
                user_schema = _resolve_user_target_schema(username=args.username)
                print(
                    f"Usuário '{args.username}' salvo com sucesso. Schema: {user_schema}"
                )
            else:
                raise SystemExit(
                    f"Usuário '{args.username}' já existe. Use --replace para atualizar a senha."
                )
        elif args.subcmd == "list":
            users = list_users(active_only=not bool(getattr(args, "all", False)))
            if not users:
                print("Nenhum usuário encontrado.")
            else:
                for username in users:
                    print(username)
        elif args.subcmd == "audit-schemas":
            rows = list_user_schema_mappings()
            if bool(getattr(args, "pending_only", False)):
                rows = [row for row in rows if str(row.get("action") or "") != "keep"]
            if not rows:
                print("Nenhuma migração pendente de schema.")
            else:
                for row in rows:
                    action = str(row.get("action") or "keep")
                    clone_note = ""
                    if (
                        action == "assign_unique"
                        and bool(row.get("legacy_schema_exists"))
                        and not bool(row.get("planned_schema_exists"))
                    ):
                        clone_note = " | clone legado sugerido"
                    print(
                        f"{row.get('username')} | atual={row.get('app_schema') or '-'} | "
                        f"planejado={row.get('planned_schema')} | legado={row.get('legacy_schema')} | "
                        f"acao={action}{clone_note}"
                    )
        elif args.subcmd == "migrate-schemas":
            try:
                report = migrate_user_app_schemas(
                    dry_run=bool(getattr(args, "dry_run", False)),
                    clone_legacy_schema=not bool(
                        getattr(args, "no_clone_legacy", False)
                    ),
                )
            except Exception as exc:
                raise SystemExit(
                    f"Falha na migração de schemas dos usuários: {exc}"
                ) from exc
            if report.get("dry_run"):
                print("Dry-run da migração de schemas:")
            else:
                print("Migração de schemas concluída.")
            for row in report.get("mappings", []):
                print(
                    f"{row.get('username')} | atual={row.get('app_schema') or '-'} | "
                    f"planejado={row.get('planned_schema')} | legado={row.get('legacy_schema')} | "
                    f"acao={row.get('action')}"
                )
            cloned = report.get("cloned_schemas", [])
            if cloned:
                print("Schemas clonados:")
                for item in cloned:
                    print(
                        f"  - {item.get('source_schema')} -> {item.get('target_schema')}"
                    )
        elif args.subcmd == "invite":
            explicit_schema = (
                sanitize_schema_name(args.target_schema) if args.target_schema else None
            )
            try:
                temp_password = issue_temporary_password(
                    username=args.username,
                    replace=bool(getattr(args, "replace", False)),
                    app_schema=explicit_schema,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc

            if loaded_env_path is not None:
                print(f".env carregado: {loaded_env_path}")
            print(f"Usuário temporário preparado: {args.username}")
            print(f"Senha de primeiro acesso: {temp_password}")
            print(
                "Envie essa senha ao cliente por canal seguro. No primeiro login, ele será obrigado a cadastrar a senha pessoal."
            )

            if bool(getattr(args, "bootstrap", False)):
                source_schema = sanitize_schema_name(args.from_schema)
                target_schema = _resolve_user_target_schema(
                    username=args.username,
                    explicit_schema=args.target_schema,
                )
                _bootstrap_user_schema(
                    source_schema=source_schema,
                    target_schema=target_schema,
                    mode=args.mode,
                )
        elif args.subcmd == "bootstrap":
            password = args.password
            if not password:
                password = getpass.getpass("Senha do usuário: ")
            explicit_schema = (
                sanitize_schema_name(args.target_schema) if args.target_schema else None
            )
            try:
                created = create_user(
                    username=args.username,
                    password=password,
                    replace=bool(getattr(args, "replace", False)),
                    app_schema=explicit_schema,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if not created and not bool(getattr(args, "replace", False)):
                raise SystemExit(
                    f"Usuário '{args.username}' já existe. Use --replace para atualizar a senha."
                )

            source_schema = sanitize_schema_name(args.from_schema)
            target_schema = _resolve_user_target_schema(
                username=args.username,
                explicit_schema=args.target_schema,
            )
            print(
                f"Bootstrap do usuário '{args.username}' em {target_schema} a partir de {source_schema}..."
            )
            _bootstrap_user_schema(
                source_schema=source_schema,
                target_schema=target_schema,
                mode=args.mode,
            )
    elif args.cmd == "service-run":
        if args.subcmd == "start":
            scheduled_for = None
            if args.scheduled_for:
                try:
                    scheduled_for = dt.datetime.fromisoformat(args.scheduled_for)
                except ValueError as exc:
                    raise SystemExit(
                        "Data/hora invalida em --scheduled-for. Use ISO 8601."
                    ) from exc
            run_id = start_service_run(
                service_key=args.service,
                trigger_type=args.trigger,
                scheduled_for=scheduled_for,
                step=args.step,
                summary=args.summary,
            )
            print(run_id)
        elif args.subcmd == "finish":
            updated = finish_service_run(
                args.run_id,
                status=args.status,
                step=args.step,
                summary=args.summary,
                error_message=args.message,
            )
            if not updated:
                raise SystemExit(
                    f"Execucao {args.run_id} nao encontrada para finalizar."
                )
            print(args.run_id)
        elif args.subcmd == "list":
            rows = list_service_runs(
                limit=int(getattr(args, "limit", 20)),
                service_key=getattr(args, "service", None),
            )
            if not rows:
                print("Nenhuma execucao registrada.")
            else:
                for row in rows:
                    started_at = str(row.get("started_at") or "")
                    finished_at = str(row.get("finished_at") or "-")
                    status = str(row.get("status") or "-")
                    service_key = str(row.get("service_key") or "-")
                    summary = str(row.get("summary") or "").strip()
                    suffix = f" | {summary}" if summary else ""
                    print(
                        f"{row.get('id')} | {service_key} | {status} | "
                        f"inicio={started_at} | fim={finished_at}{suffix}"
                    )
        elif args.subcmd == "watchdog":
            run_id = fail_latest_running_service_run(
                service_key=args.service,
                step=args.step,
                summary=args.summary,
                error_message=args.message,
            )
            print(run_id or "noop")
    elif args.cmd == "db":
        if args.subcmd == "check":
            report = run_db_check(timeout_seconds=float(args.timeout))
            if loaded_env_path is not None:
                print(f".env carregado: {loaded_env_path}")
            print(f"Runtime atual: PostgreSQL ({report['runtime_target']})")

            if report.get("postgres_configured"):
                source = report.get("postgres_source") or "desconhecida"
                print(f"PostgreSQL configurado via: {source}")
                print(f"Destino PostgreSQL: {report.get('postgres_target')}")
                if report.get("tcp_ok") is not None:
                    tcp_status = "OK" if report["tcp_ok"] else "falhou"
                    print(
                        f"Teste TCP host/porta: {tcp_status} ({report.get('tcp_message')})"
                    )
                if report.get("sql_ok") is not None:
                    sql_status = "OK" if report["sql_ok"] else "falhou"
                    print(
                        f"Teste SQL (SELECT 1): {sql_status} ({report.get('sql_message')})"
                    )
            else:
                print("PostgreSQL não está configurado.")

            if not is_postgres_ready(report):
                for err in report.get("errors", []):
                    print(f"- {err}")
                print(
                    "Banco remoto ainda não está pronto para migração. "
                    "Corrija os itens acima e rode: opcoes db check"
                )
                raise SystemExit(1)

            print(
                "Conectividade PostgreSQL validada. "
                "Ambiente pronto para operação em PostgreSQL."
            )
        elif args.subcmd == "optimize":
            schema_name = (
                sanitize_schema_name(args.schema)
                if args.schema
                else _resolve_user_target_schema(username=args.username)
            )
            if loaded_env_path is not None:
                print(f".env carregado: {loaded_env_path}")
            print(f"Schema alvo: {schema_name}")
            print("Aplicando índices recomendados...")
            try:
                report = optimize_postgres_schema(
                    schema=schema_name,
                    include_analyze=not bool(getattr(args, "no_analyze", False)),
                )
            except Exception as exc:
                raise SystemExit(f"Falha no optimize: {exc}") from exc

            print(f"Destino PostgreSQL: {report.get('postgres_target')}")
            for sql in report.get("applied", []):
                print(f"  - OK: {sql}")
            for item in report.get("skipped", []):
                print(f"  - SKIP: {item}")
            analyzed = report.get("analyzed", [])
            if analyzed:
                print("ANALYZE executado em:")
                for table in analyzed:
                    print(f"  - {table}")
            print("Optimize concluído.")
        elif args.subcmd == "migrate":
            source_dsn = args.source_dsn
            if not source_dsn:
                source_target, source_errors = resolve_postgres_target()
                if source_target is None:
                    details = (
                        "; ".join(source_errors)
                        if source_errors
                        else "configuração ausente"
                    )
                    raise SystemExit(
                        f"Falha ao resolver origem no .env local: {details}"
                    )
                source_dsn = source_target.dsn

            if loaded_env_path is not None:
                print(f".env carregado: {loaded_env_path}")
            print("Iniciando migração PostgreSQL -> PostgreSQL...")
            try:
                report = migrate_postgres(
                    source_dsn=source_dsn,
                    target_dsn=args.target_dsn,
                    source_app_schema=sanitize_schema_name(args.source_app_schema),
                    target_app_schema=sanitize_schema_name(args.target_app_schema),
                    source_auth_schema=sanitize_schema_name(args.source_auth_schema),
                    target_auth_schema=sanitize_schema_name(args.target_auth_schema),
                    truncate_target=not bool(getattr(args, "no_truncate", False)),
                )
            except Exception as exc:
                raise SystemExit(f"Falha na migração: {exc}") from exc

            print(f"Origem:  {report['source']}")
            print(f"Destino: {report['target']}")
            print(
                "Modo destino: "
                + (
                    "TRUNCATE + cópia integral"
                    if report.get("truncate_target")
                    else "cópia sem truncate"
                )
            )
            print("Tabelas migradas:")
            for item in report.get("tables", []):
                print(
                    f"  - {item['source_schema']}.{item['table']} -> "
                    f"{item['target_schema']}.{item['table']} ({item['rows']} linhas)"
                )
            print(f"Total de linhas copiadas: {report.get('total_rows', 0)}")
            print("Migração concluída com contagem validada.")
    elif args.cmd == "fundamentus":
        snap = None
        if args.snapshot_date:
            snap = _parse_trade_date(args.snapshot_date)
        try:
            count = scrape_and_store(
                pl_min=args.pl_min,
                patrim_min=args.patrim_min,
                timeout=args.timeout,
                snapshot_date=snap,
            )
        except FundamentusSchemaError as exc:
            raise SystemExit(
                "Fundamentus: estrutura de origem incompatível; nenhum dado foi gravado. "
                f"Detalhe: {exc}"
            ) from exc
        print(
            f"Fundamentus: {count} linhas gravadas no snapshot {snap or dt.date.today().isoformat()}."
        )
    elif args.cmd == "fundamentus-filter":
        snap = None
        if args.snapshot_date:
            snap = _parse_trade_date(args.snapshot_date)
        cfg = FundamentusFilterConfig(
            liq_2m_min=args.liq_2m_min,
            div_bruta_patrim_max=args.div_bruta_patrim_max,
            cresc_rec_5a_min=args.cresc_rec_5a_min,
            div_yield_min=args.div_yield_min,
            roe_min=args.roe_min,
            margem_liquida_min=args.margem_liquida_min,
            margem_liquida_allow_zero=not args.no_margem_liquida_zero,
        )
        results = apply_filters(snapshot_date=snap, cfg=cfg)
        if results["total"] == 0:
            print("Fundamentus: nenhum snapshot disponível para filtrar.")
        else:
            used_snap = snap or latest_snapshot_date()
            print(
                "Fundamentus filtros: "
                f"{results['approved']} aprovadas, {results['rejected']} reprovadas "
                f"(total {results['total']}) no snapshot {used_snap}."
            )
    elif args.cmd == "fundamentus-integrity":
        if args.fundamentus_integrity_action == "list":
            rows = list_quarantined_snapshots()
            if not rows:
                print("Fundamentus: nenhum snapshot em quarentena.")
            else:
                print("Fundamentus: snapshots em quarentena:")
                for row in rows:
                    print(
                        f"  - {row['snapshot_date']}: {row.get('reason') or 'Sem motivo informado.'}"
                    )
        elif args.fundamentus_integrity_action == "quarantine":
            try:
                count = quarantine_snapshots(
                    start_date=args.from_date,
                    end_date=args.to_date,
                    reason=args.reason,
                )
            except ValueError as exc:
                raise SystemExit(
                    f"Fundamentus: quarentena não aplicada. {exc}"
                ) from exc
            print(f"Fundamentus: {count} snapshots colocados em quarentena.")
    elif args.cmd == "repair":
        if args.subcmd == "covered-call-exercise-fee":
            try:
                report = repair_covered_call_exercise_sale_fee(
                    call_position_id=args.call_position_id,
                    stock_position_id=args.stock_position_id,
                    sale_fees=args.sale_fees,
                    apply=bool(args.apply),
                )
            except ExerciseFeeRepairError as exc:
                raise SystemExit(f"Correcao nao aplicada: {exc}") from exc
            mode = "APLICADA" if report["applied"] else "SIMULACAO"
            print(f"Correcao de taxa de CALL exercida: {mode}")
            print(
                f"  CALL #{report['call_position_id']} | historico #{report['stock_position_id']} | "
                f"evento #{report['holding_event_id']} | SELL #{report['sell_ledger_id']}"
            )
            print(
                f"  Bruto: R$ {report['gross_sale']:.2f} | despesas: R$ {report['sale_fees']:.2f} | "
                f"liquido: R$ {report['net_sale']:.2f}"
            )
            print(
                "  Ajustes necessarios: "
                f"evento={'sim' if report['update_holding_event'] else 'nao'}, "
                f"SELL={'sim' if report['update_sell_ledger'] else 'nao'}"
            )
    else:
        raise SystemExit(f"Comando desconhecido: {args.cmd}")


def _parse_trade_date(value: str) -> str:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:  # noqa: F841
        raise SystemExit("Data inválida. Use o formato YYYY-MM-DD.") from exc
    return parsed.isoformat()


def _format_currency(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _format_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _print_positions(positions: List[dict]) -> None:
    header = (
        f"{'ID':>4} {'Ticker':<10} {'Data':<10} {'Qtd':>5} "
        f"{'Preço':>10} {'Último':>10} {'P/L':>12} {'P/L%':>8} {'Score':>5} {'Trend':>5}"
    )
    print(header)
    print("-" * len(header))
    for pos in positions:
        print(
            f"{pos['id']:>4} "
            f"{pos['ticker']:<10} "
            f"{pos['trade_date']:<10} "
            f"{pos['qty']:>5d} "
            f"{_format_currency(pos['entry_price']):>10} "
            f"{_format_currency(pos['last_price']):>10} "
            f"{_format_currency(pos['pl']):>12} "
            f"{_format_percent(pos['pl_pct']):>8} "
            f"{_format_number(pos.get('score_total'), digits=2):>5} "
            f"{(pos['trend_flag'] or '-'):>5}"
        )


def _format_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        if isinstance(value, str):
            text = value.strip()
            if not text or text == "-":
                return "-"
            cleaned = (
                text.replace("%", "")
                .replace("+", "")
                .replace("\u2212", "-")
                .replace("−", "-")
            )
            # Trata números pt-BR com vírgula decimal.
            cleaned = cleaned.replace(".", "").replace(",", ".")
            num = float(cleaned)
        else:
            num = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{num:.{digits}f}"


def _print_report(data) -> None:
    print(f"Snapshot mais recente: {data.snapshot_date}")
    print("\nTop oportunidades:")
    if not data.opportunities:
        print("  Nenhuma opção com score dentro do filtro.")
    else:
        header = (
            f"{'Ticker':<10} {'Und':<6} {'Score':>5} {'Último':>9} {'Ask':>9} "
            f"{'Spr%':>6} {'Illq':>5} {'Justo':>9} {'Dist%':>7} {'%2x':>8} {'Custo%':>8} {'ExtR$':>7} {'Ext%':>6} {'BE':>8} {'BE%':>7} {'Pbe%':>6} {'IV%':>6} {'IVr':>5} {'HVw':>4} {'HVref':>6} {'IV-HV':>7} {'IVs':>4} {'EM2x':>5} {'Fluxo':>8}"
        )
        print(header)
        print("-" * len(header))
        for opp in data.opportunities:
            hv_window = opp.get("hv_ref_window")
            hv_window_str = "-"
            if hv_window is not None:
                try:
                    hv_window_str = str(int(hv_window))
                except (TypeError, ValueError):
                    hv_window_str = "-"
            print(
                f"{opp['ticker']:<10} {opp['underlying']:<6} "
                f"{_format_number(opp.get('score_total'), digits=2):>5} "
                f"{_format_currency(opp['ultimo']):>9} "
                f"{_format_currency(opp.get('best_ask')):>9} "
                f"{_format_number(opp.get('spread_pct'), digits=1):>6} "
                f"{('Y' if opp.get('illiquidez_flag') else '-'):>5} "
                f"{_format_currency(opp.get('preco_teorico')):>9} "
                f"{_format_number(opp.get('distorcao_preco_pct'), digits=1):>7} "
                f"{_format_number(opp.get('%_Alta_p_2x')):>8} "
                f"{_format_number(opp.get('custo_pct')):>8} "
                f"{_format_currency(opp.get('extrinsic_value')):>7} "
                f"{_format_number(opp.get('extrinsic_pct_spot')):>6} "
                f"{_format_currency(opp.get('breakeven_price')):>8} "
                f"{_format_number(opp.get('breakeven_dist_pct')):>7} "
                f"{_format_number(opp.get('prob_be_pct'), digits=1):>6} "
                f"{_format_number(opp.get('vol_impl_perc')):>6} "
                f"{_format_number(opp.get('iv_rank_180d'), digits=1):>5} "
                f"{hv_window_str:>4} "
                f"{_format_number(opp.get('hv_ref')):>6} "
                f"{_format_number(opp.get('iv_hv_spread')):>7} "
                f"{(opp.get('iv_score') if opp.get('iv_score') is not None else '-'):>4} "
                f"{(opp.get('em2x_score') if opp.get('em2x_score') is not None else '-'):>5} "
                f"{_format_number(opp.get('vol_fluxo_5d')):>8}"
            )
    print(
        "\nOportunidades recorrentes "
        f"(últimos {data.recurring_window_days} dias, {data.recurring_snapshot_days} snapshots desde {data.recurring_window_start}):"
    )
    if not data.recurring_opportunities:
        print("  Nenhuma recorrência dentro da janela.")
    else:
        header = (
            f"{'Ticker':<10} {'Und':<6} {'Dias':>5} {'Presença':>9} {'Última':>10} "
            f"{'Score':>6} {'Último':>10} {'%2x':>8} {'Spot':>8}"
        )
        print(header)
        print("-" * len(header))
        for opp in data.recurring_opportunities:
            presence = (
                f"{opp['presence_pct']:.0f}%"
                if opp.get("presence_pct") is not None
                else "-"
            )
            print(
                f"{opp['ticker']:<10} {opp['underlying']:<6} "
                f"{opp['hits']:>5d} "
                f"{presence:>9} "
                f"{(opp.get('last_seen') or '-'):>10} "
                f"{_format_number(opp.get('score_total'), digits=2):>6} "
                f"{_format_currency(opp.get('ultimo')):>10} "
                f"{_format_number(opp.get('%_Alta_p_2x')):>8} "
                f"{_format_number(opp.get('underlying_price')):>8}"
            )
    print("\nTop Apostas Racionais (até 5):")
    if not data.rational_opportunities:
        print("  Nenhuma dentro do filtro.")
    else:
        header = f"{'Ticker':<10} {'Und':<6} {'Score':>6} {'Prob%':>7} {'Extr%':>7} {'%2x':>8} {'Custo%':>8} {'Dias':>5}"
        print(header)
        print("-" * len(header))
        for opp in data.rational_opportunities:
            prob = opp.get("prob_itm_pct")
            print(
                f"{opp['ticker']:<10} {opp['underlying']:<6} "
                f"{_format_number(opp.get('score_total'), digits=2):>6} "
                f"{_format_number(prob, digits=1):>7} "
                f"{_format_number(opp.get('extrinsic_pct_spot'), digits=1):>7} "
                f"{_format_number(opp.get('%_Alta_p_2x'), digits=1):>8} "
                f"{_format_number(opp.get('custo_pct'), digits=1):>8} "
                f"{(opp.get('dias_uteis') or '-'):>5}"
            )
    print("\nTop Loterias (até 5):")
    if not data.lottery_opportunities:
        print("  Nenhuma dentro do filtro.")
    else:
        header = f"{'Ticker':<10} {'Und':<6} {'Score':>6} {'Prob%':>7} {'Extr%':>7} {'%2x':>8} {'Custo%':>8} {'Dias':>5}"
        print(header)
        print("-" * len(header))
        for opp in data.lottery_opportunities:
            prob = opp.get("prob_itm_pct")
            print(
                f"{opp['ticker']:<10} {opp['underlying']:<6} "
                f"{_format_number(opp.get('score_total'), digits=2):>6} "
                f"{_format_number(prob, digits=1):>7} "
                f"{_format_number(opp.get('extrinsic_pct_spot'), digits=1):>7} "
                f"{_format_number(opp.get('%_Alta_p_2x'), digits=1):>8} "
                f"{_format_number(opp.get('custo_pct'), digits=1):>8} "
                f"{(opp.get('dias_uteis') or '-'):>5}"
            )
    print("\nPosições abertas:")
    positions = data.positions
    if not positions:
        print("  Nenhuma posição aberta.")
    else:
        _print_positions(positions)
    if data.alerts:
        print("\nAlertas:")
        for alert in data.alerts:
            pos = alert["position"]
            reasons = "; ".join(alert["reasons"])
            print(f"  - {pos['ticker']} ({pos['trade_date']}): {reasons}")
    else:
        print("\nAlertas: nenhum.")


def _print_decisions(rows: List[dict]) -> None:
    header = (
        f"{'ID':>4} {'Ticker':<10} {'Snap':<10} {'Venc':<10} {'Strike':>8} "
        f"{'Ask':>8} {'Bid':>8} {'Theo':>8} {'Score':>6} {'Notes'}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.get('id', ''):>4} "
            f"{str(r.get('ticker') or ''):<10} "
            f"{str(r.get('snapshot_date') or ''):<10} "
            f"{str(r.get('vencimento') or ''):<10} "
            f"{_format_currency(r.get('strike')):>8} "
            f"{_format_currency(r.get('best_ask')):>8} "
            f"{_format_currency(r.get('best_bid')):>8} "
            f"{_format_currency(r.get('preco_teorico')):>8} "
            f"{_format_number(r.get('score_total'), digits=2):>6} "
            f"{str(r.get('notes') or '')}"
        )


if __name__ == "__main__":
    main()
