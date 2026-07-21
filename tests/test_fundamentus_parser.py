import pytest

from opcoes.fundamentus import (
    FundamentusSchemaError,
    normalize_rows,
    parse_result_table,
    scrape_and_store,
)


OLD_HEADERS = [
    "Papel",
    "Cotacao",
    "P/L",
    "P/VP",
    "PSR",
    "Div.Yield",
    "P/Ativo",
    "P/Cap.Giro",
    "P/EBIT",
    "P/Ativ Circ.Liq",
    "EV/EBIT",
    "EV/EBITDA",
    "Mrg Ebit",
    "Mrg. Liq.",
    "Liq. Corr.",
    "ROIC",
    "ROE",
    "Liq.2meses",
    "Patrim. Liq",
    "Div.Brut/ Patrim.",
    "Cresc. Rec.5a",
]

CURRENT_HEADERS = [
    *OLD_HEADERS[:12],
    "Mrg Bruta",
    *OLD_HEADERS[12:-2],
    "Dív.Líq/ Patrim.",
    OLD_HEADERS[-1],
]


def _build_html_row(cells: list[str]) -> str:
    tds = "".join(f"<td>{cell}</td>" for cell in cells)
    return f"<tr>{tds}</tr>"


def _build_html(headers: list[str], cells: list[str]) -> str:
    header_cells = "".join(f"<th>{header}</th>" for header in headers)
    return f"""
    <html>
      <body>
        <table id="resultado">
          <thead><tr>{header_cells}</tr></thead>
          <tbody>{_build_html_row(cells)}</tbody>
        </table>
      </body>
    </html>
    """


def test_parse_result_table_and_normalize_old_schema() -> None:
    cells = [
        '<span class="tips"><a href="detalhes.php?papel=MNPR3">MNPR3</a></span>',
        "4,56",
        "0,62",
        "1,61",
        "0,757",
        "0,00%",
        "0,734",
        "2,08",
        "4,18",
        "-52,25",
        "2,64",
        "2,33",
        "18,12%",
        "121,81%",
        "3,01",
        "25,67%",
        "258,34%",
        "169.282,00",
        "201.583.000,00",
        "0,00",
        "6,23%",
    ]

    rows = parse_result_table(_build_html(OLD_HEADERS, cells))

    assert len(rows) == 1
    assert rows[0]["papel"] == "MNPR3"
    assert rows[0]["pl"] == "0,62"

    normalized = normalize_rows(rows)
    assert len(normalized) == 1
    row = normalized[0]
    assert row["papel"] == "MNPR3"
    assert row["cotacao"] == 4.56
    assert row["div_yield"] == 0.0
    assert row["patrimonio_liq"] == 201583000.0


def test_parse_result_table_maps_current_headers_by_name() -> None:
    cells = [
        "ECOM3",
        "1,02",
        "0,47",
        "0,40",
        "2,003",
        "0,00%",
        "0,358",
        "3,59",
        "-0,66",
        "7,13",
        "-0,60",
        "-0,69",
        "18,75%",
        "-301,23%",
        "424,96%",
        "3,07",
        "-56,65%",
        "85,56%",
        "21.656,20",
        "102.037.000,00",
        "-0,04",
        "-31,35%",
    ]

    rows = parse_result_table(_build_html(CURRENT_HEADERS, cells))
    normalized = normalize_rows(rows)

    assert rows[0]["margem_ebit"] == "-301,23%"
    assert rows[0]["margem_liquida"] == "424,96%"
    assert rows[0]["liquidez_2m"] == "21.656,20"
    assert rows[0]["patrimonio_liq"] == "102.037.000,00"
    assert normalized[0]["liquidez_2m"] == 21656.2
    assert normalized[0]["patrimonio_liq"] == 102037000.0


def test_parse_result_table_rejects_unknown_header() -> None:
    headers = [*CURRENT_HEADERS, "Indicador novo"]
    cells = [str(index) for index in range(len(headers))]

    with pytest.raises(FundamentusSchemaError, match="cabecalho desconhecido"):
        parse_result_table(_build_html(headers, cells))


def test_scrape_and_store_rejects_empty_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.fundamentus.fetch_fundamentus_results", lambda **_kwargs: []
    )

    with pytest.raises(FundamentusSchemaError, match="tabela vazia"):
        scrape_and_store()
