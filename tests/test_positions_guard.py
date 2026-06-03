from __future__ import annotations

from opcoes import finance
from opcoes.positions_guard import audit_positions_page


def test_positions_guard_allows_documented_covered_call_stock_consolidation() -> None:
    positions = [
        {
            "id": 43,
            "ticker": "GGBR4",
            "underlying": "GGBR4",
            "trade_date": "2026-03-20",
            "qty": 800,
            "entry_price": 21.46,
            "fees": 0.0,
            "trade_type": "stock",
            "side": "long",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": None,
            "exit_reason": "Consolidado no exercicio da call GGBRE228",
            "strategy_tag": "covered_call",
            "notes": "Baixa economica registrada na posicao 55.",
            "is_simulated": 0,
        },
        {
            "id": 54,
            "ticker": "GGBRE228",
            "underlying": "GGBR4",
            "trade_date": "2026-04-22",
            "qty": 800,
            "entry_price": 0.36,
            "fees": 0.37,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        },
    ]

    issues = audit_positions_page(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.SELL.value: 18056.0,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        holding_events=[
            {
                "related_position_id": 54,
                "ticker": "GGBR4",
                "event_type": "CALL_EXERCISE",
            }
        ],
    )

    assert not [issue for issue in issues if issue.position_id == 43]


def test_positions_guard_flags_closed_position_without_exit_price() -> None:
    positions = [
        {
            "id": 99,
            "ticker": "PETR4",
            "underlying": "PETR4",
            "trade_date": "2026-02-19",
            "qty": 100,
            "entry_price": 31.9,
            "fees": 0.0,
            "trade_type": "stock",
            "side": "long",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": None,
            "exit_reason": "Venda manual",
            "strategy_tag": "estoque",
            "is_simulated": 0,
        }
    ]

    issues = audit_positions_page(positions, ledger_sums={})

    assert [(issue.position_id, issue.code) for issue in issues] == [
        (99, "FECHADA_SEM_PRECO")
    ]


def test_positions_guard_allows_option_expiration_without_exit_price() -> None:
    positions = [
        {
            "id": 44,
            "ticker": "BBASP226",
            "underlying": "BBAS3",
            "trade_date": "2026-03-23",
            "qty": 400,
            "entry_price": 0.20,
            "fees": 0.19,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-04-17",
            "exit_price": None,
            "exit_reason": "Expiracao",
            "strategy_tag": "cash_put",
            "is_simulated": 0,
        }
    ]

    issues = audit_positions_page(
        positions,
        ledger_sums={
            44: {
                finance.TransactionType.PREMIUM.value: 79.81,
                finance.TransactionType.REALIZED.value: 79.81,
            }
        },
    )

    assert not issues


def test_positions_guard_flags_open_position_with_exit_fields() -> None:
    positions = [
        {
            "id": 100,
            "ticker": "PETR4",
            "underlying": "PETR4",
            "trade_date": "2026-02-19",
            "qty": 100,
            "entry_price": 31.9,
            "fees": 0.0,
            "trade_type": "stock",
            "side": "long",
            "status": "open",
            "exit_date": "2026-05-15",
            "exit_price": None,
            "strategy_tag": "estoque",
            "is_simulated": 0,
        }
    ]

    issues = audit_positions_page(positions, ledger_sums={})

    assert [(issue.position_id, issue.code) for issue in issues] == [
        (100, "ABERTA_COM_SAIDA")
    ]
