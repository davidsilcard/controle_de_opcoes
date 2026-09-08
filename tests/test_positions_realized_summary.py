from __future__ import annotations

from html.parser import HTMLParser

import pytest

from opcoes import portfolio
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self.tables:
            self.tables[-1].append(self._row)


def _close_position(position_id: int, *, exit_date: str, exit_price: float) -> None:
    portfolio.update_position(
        position_id=position_id,
        status="closed",
        exit_date=exit_date,
        exit_price=exit_price,
    )


def test_positions_page_shows_realized_results_by_month_and_year() -> None:
    pos_profit = portfolio.add_position(
        ticker="PETR4",
        underlying="PETR4",
        trade_date="2026-03-01",
        qty=100,
        entry_price=10.0,
        fees=0.0,
        side="long",
        trade_type="swing",
        strategy_tag="ranking",
    )
    _close_position(pos_profit, exit_date="2026-03-10", exit_price=12.0)

    pos_loss = portfolio.add_position(
        ticker="VALE3",
        underlying="VALE3",
        trade_date="2026-03-02",
        qty=50,
        entry_price=10.0,
        fees=0.0,
        side="long",
        trade_type="swing",
        strategy_tag="ranking",
    )
    _close_position(pos_loss, exit_date="2026-03-15", exit_price=9.0)

    pos_other_month = portfolio.add_position(
        ticker="ITUB4",
        underlying="ITUB4",
        trade_date="2026-02-01",
        qty=10,
        entry_price=10.0,
        fees=0.0,
        side="long",
        trade_type="swing",
        strategy_tag="ranking",
    )
    _close_position(pos_other_month, exit_date="2026-02-20", exit_price=11.0)

    app = create_app()
    app.testing = True
    client = app.test_client()

    resp = client.get("/positions?result_year=2026&result_month=3")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert "Resultados realizados" in html
    assert "Operações encerradas no período" in html
    assert "03/2026" in html
    assert "2026" in html
    assert "R$ 150.00" in html

    parsed = _TableParser()
    parsed.feed(html)
    by_month = next(table for table in parsed.tables if table[0][0] == "Mês")
    assert ["03/2026", "2", "150.00", "0.00", "150.00"] in by_month
    assert ["02/2026", "1", "10.00", "0.00", "10.00"] in by_month
    by_year = next(table for table in parsed.tables if table[0][0] == "Ano")
    assert ["2026", "3", "160.00", "0.00", "160.00"] in by_year

    details = next(
        table
        for table in parsed.tables
        if table[0]
        == [
            "Saída",
            "Ticker",
            "Ativo",
            "Estratégia",
            "Motivo",
            "Qtd",
            "Bruto",
            "Taxas",
            "Fiscal",
        ]
    )
    assert details[1:] == [
        [
            "2026-03-15",
            "VALE3",
            "VALE3",
            "ranking",
            "-",
            "50",
            "-50.00",
            "0.00",
            "-50.00",
        ],
        [
            "2026-03-10",
            "PETR4",
            "PETR4",
            "ranking",
            "-",
            "100",
            "200.00",
            "0.00",
            "200.00",
        ],
    ]
