"""Exercise production Fundamentus templates and JS without database or network.

Install Chromium with `uv run playwright install chromium`. The CI requires
the browser; local runs may skip only when no executable has been installed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from flask import Flask, render_template
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _context() -> dict:
    numeric = dict.fromkeys(
        "cotacao preco_teto pl pvp psr p_ativo p_cap_giro p_ebit p_ativo_circ_liq "
        "ev_ebit ev_ebitda div_yield margem_ebit margem_liquida liquidez_corrente "
        "roic roe liquidez_2m patrimonio_liq div_bruta_patrim cresc_rec_5a peg_ratio".split(),
        1.0,
    )
    rows = []
    for papel, cotacao, pl, dy, roe in [
        ("PETR4", 37.5, 5.0, 12.34, 20.0),
        ("VALE3", 0.0, -5.25, 0.0, 15.0),
        ("WEGE3", None, 10.0, None, None),
        ("BBAS3", 1050.25, 7.0, 8.0, 10.0),
    ]:
        rows.append(
            {
                **numeric,
                "papel": papel,
                "cotacao": cotacao,
                "pl": pl,
                "div_yield": dy,
                "roe": roe,
                "sector": "Energia; Serviços",
                "signal": {
                    "status": "approved",
                    "reason": "approved",
                    "failed_step": 0,
                    "reason_label": '=EXEMPLO("teste"); descrição\nsegunda linha',
                },
            }
        )
    puts = []
    for papel, score, source in [("PETR4", 7.5, "best_bid"), ("BBAS3", 9.0, "last")]:
        puts.append(
            {
                "papel": papel,
                "contrato": f"{papel}PUT",
                "cotacao": 37.5,
                "strike": 34.0,
                "preco_ref": 0.8,
                "premium_source": source,
                "premio_pct": 2.1,
                "premio_mensal_pct": 2.1,
                "distancia_strike_pct": 9.0,
                "put_score": score,
                "put_profile": "Equilibrada",
                "execution_note": "Acompanha book",
                "dias_ate_vencimento": 18,
            }
        )
    return {
        "message": "Dados sintéticos de teste",
        "snapshot_date": "2026-10-08",
        "rows": rows,
        "total_rows": 4,
        "filtered_rows_count": 4,
        "signals_available": True,
        "status_filter": "all",
        "status_label": "Todas",
        "approved_count": 4,
        "rejected_count": 0,
        "limit": None,
        "ranking_window_days": 30,
        "ranking_total": [],
        "ranking_window": [],
        "changes_reference_date": "2026-10-07",
        "entered_opportunities": ["PETR4"],
        "exited_opportunities": [],
        "target_yield_pct": 8.0,
        "sector_breakdown": [
            {"label": "Energia", "count": 4, "pct": 100.0, "color": "#4e79a7"}
        ],
        "put_target_vencimento": "16/10/2026",
        "put_snapshot_date": "2026-10-07",
        "put_score_formula": "score didático",
        "put_min_premium_pct": 0.5,
        "put_min_score": 4.0,
        "put_watchlist_count": 1,
        "put_profile_breakdown": [],
        "put_opportunities": puts,
        "put_distance_limit_pct": 15,
        "put_target_monthly_yield_pct": 1.0,
    }


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        installed_chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        if not executable.exists() and installed_chrome.exists():
            executable = installed_chrome
        if not executable.exists():
            if os.getenv("OPCOES_REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail("Chromium obrigatório para os testes de UI no CI")
            pytest.skip("Instale Chromium: uv run playwright install chromium")
        instance = playwright.chromium.launch(
            headless=True, executable_path=str(executable)
        )
        yield instance
        instance.close()


@pytest.fixture
def ui(browser):
    app = Flask("fundamentus_ui", template_folder=str(ROOT / "opcoes/templates"))
    with app.test_request_context("/fundamentus"):
        context = _context()
        shell = render_template("fundamentus.html", **context)
        partial = render_template("partials/fundamentus_dashboard.html", **context)
    start = shell.index('        <div class="card border-0 shadow-sm">')
    end = shell.index("      </div>\n    </main>", start)
    html = shell[:start] + partial + shell[end:]
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def respond(route):
        url = route.request.url
        if "/static/fundamentus_table." in url:
            path = ROOT / "opcoes/static" / url.rsplit("/", 1)[1]
            route.fulfill(
                path=path,
                content_type="text/javascript" if path.suffix == ".js" else "text/css",
            )
        elif url == "http://fundamentus.test/":
            route.fulfill(body=html, content_type="text/html")
        elif url.endswith("bootstrap@5.3.3/dist/css/bootstrap.min.css"):
            route.fulfill(
                path=ROOT / "tests/assets/bootstrap-5.3.3.min.css",
                content_type="text/css",
            )
        else:
            # Keep browser tests independent of CDNs. Production markup is unchanged.
            route.fulfill(
                body="", content_type="text/javascript" if "htmx" in url else "text/css"
            )

    page.route("**/*", respond)
    page.goto("http://fundamentus.test/")
    page.wait_for_selector('[data-grid-ready="true"]')
    page.fundamentus_partial = partial
    page.evaluate(
        """() => {
      window.copied = [];
      Object.defineProperty(navigator, 'clipboard', {configurable:true,
        value:{writeText: async text => { window.copied.push(text); }}});
    }"""
    )
    yield page
    assert errors == []
    page.close()


def _rows(grid) -> list[str]:
    return grid.locator(
        'tbody tr:not([hidden]) td[data-key="papel"]'
    ).all_text_contents()


def test_sort_filter_and_put_independence(ui):
    fund = ui.locator('[data-grid-name="indicadores"]')
    put = ui.locator('[data-grid-name="puts"]')
    assert fund.locator("thead tr:first-child th[data-key]").count() == 27
    assert put.locator("thead tr:first-child th[data-key]").count() == 13
    assert _rows(put) == ["BBAS3", "PETR4"]
    fund.locator('button[data-key="cotacao"]').click()
    assert _rows(fund) == ["VALE3", "PETR4", "BBAS3", "WEGE3"]
    fund.locator('button[data-key="cotacao"]').click()
    assert _rows(fund) == ["BBAS3", "PETR4", "VALE3", "WEGE3"]
    assert (
        fund.locator('th[aria-sort="descending"]').get_attribute("data-key")
        == "cotacao"
    )
    fund.locator('.column-filter[data-key="div_yield"]').fill(">=8")
    fund.locator('.column-filter[data-key="roe"]').fill(">10")
    assert _rows(fund) == ["PETR4"]
    assert _rows(put) == ["BBAS3", "PETR4"]
    fund.locator(".grid-clear-filters").click()
    for operator, expected in [
        ("=0", ["VALE3"]),
        ("<=0", ["VALE3"]),
        ("<1", ["VALE3"]),
        (">=37,5", ["BBAS3", "PETR4"]),
    ]:
        fund.locator('.column-filter[data-key="cotacao"]').fill(operator)
        assert _rows(fund) == expected
    fund.locator('.column-filter[data-key="cotacao"]').fill("")
    fund.locator('.column-filter[data-key="papel"]').fill("petr")
    assert _rows(fund) == ["PETR4"]


def test_selection_copy_formats_and_missing_values(ui):
    fund = ui.locator('[data-grid-name="indicadores"]')
    fund.locator('button[data-key="cotacao"]').click()
    fund.locator(".grid-select-all").check()
    fund.locator('[data-format="tsv"]').click()
    lines = ui.evaluate("window.copied.at(-1)").splitlines()
    assert len(lines) == 5
    headers = lines[0].split("\t")
    assert len(headers) == 27 and headers[0] == "Papel" and "▲" not in lines[0]
    records = {line.split("\t")[0]: line.split("\t") for line in lines[1:]}
    assert records["VALE3"][1] == "0,00"
    assert records["VALE3"][3] == "-5,25"
    assert records["PETR4"][6] == "12,34%"
    assert records["WEGE3"][1] == ""
    assert records["BBAS3"][1] == "1050,25"
    assert records["PETR4"][24].startswith("'=EXEMPLO")
    assert records["PETR4"][25] == "0"
    assert [line.split("\t")[0] for line in lines[1:]] == [
        "VALE3",
        "PETR4",
        "BBAS3",
        "WEGE3",
    ]
    fund.locator(".grid-clear-selection").click()
    fund.locator(
        'tr:has(td[data-key="papel"]:text-is("PETR4")) .grid-row-select'
    ).check()
    assert fund.locator(".grid-select-all").evaluate("el => el.indeterminate")
    fund.locator('[data-format="text"]').click()
    text = ui.evaluate("window.copied.at(-1)")
    assert "Papel: PETR4" in text and "2026-10-08" in text and "VALE3" not in text
    fund.locator('.column-filter[data-key="papel"]').fill("VALE")
    assert fund.locator('[data-format="tsv"]').is_disabled()
    assert "fora do filtro" in fund.locator(".grid-selection-note").inner_text()
    fund.locator(".grid-scope").select_option("filtered")
    fund.locator('[data-format="tsv"]').click()
    assert "VALE3" in ui.evaluate("window.copied.at(-1)")


def test_hidden_columns_filters_preferences_and_htmx(ui):
    fund = ui.locator('[data-grid-name="indicadores"]')
    fund.locator('.column-filter[data-key="psr"]').fill(">=1")
    fund.locator(".grid-profile").select_option("essential")
    assert fund.locator("thead tr:first-child th:not([hidden])[data-key]").count() == 10
    assert fund.locator('thead tr:nth-child(2) th[data-key="psr"]').is_hidden()
    assert "coluna oculta" in fund.locator(".grid-active-filters").inner_text()
    fund.locator('[data-format="tsv"]').click()
    assert len(ui.evaluate("window.copied.at(-1)").splitlines()[0].split("\t")) == 10
    fund.locator(".grid-export-columns").select_option("all")
    fund.locator('[data-format="tsv"]').click()
    assert len(ui.evaluate("window.copied.at(-1)").splitlines()[0].split("\t")) == 27
    ui.evaluate(
        """() => {
      const grid = document.querySelector('[data-grid-name="indicadores"]');
      document.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles:true}));
      window.initFundamentusInteractive(grid);
      window.initFundamentusInteractive(grid);
    }"""
    )
    # Duplicate listeners would toggle direction twice and break this assertion.
    fund.locator('button[data-key="cotacao"]').click()
    assert _rows(fund)[0] == "VALE3"
    ui.reload()
    ui.wait_for_selector('[data-grid-ready="true"]')
    assert fund.locator(".grid-profile").input_value() == "essential"
    assert fund.locator('.column-filter[data-key="psr"]').input_value() == ""
    assert not fund.locator(".grid-select-all").is_checked()


def test_clipboard_denial_csv_and_put_context(ui, workspace_tmp_path):
    fund = ui.locator('[data-grid-name="indicadores"]')
    ui.evaluate(
        "() => { navigator.clipboard.writeText = async () => { throw new Error('denied'); }; }"
    )
    fund.locator('[data-format="tsv"]').click()
    assert fund.locator("dialog").is_visible()
    assert "0,00" in fund.locator("textarea").input_value()
    assert "linhas copiadas" not in fund.locator(".grid-feedback").inner_text()
    assert fund.locator("textarea").evaluate(
        "el => el.selectionStart === 0 && el.selectionEnd === el.value.length"
    )
    fund.locator(".grid-close-dialog").click()
    with ui.expect_download() as download_info:
        fund.locator('[data-format="csv"]').click()
    download = download_info.value
    assert "2026-10-08" in download.suggested_filename
    path = workspace_tmp_path / "export.csv"
    download.save_as(path)
    text = path.read_text(encoding="utf-8-sig")
    assert '"Energia; Serviços"' in text and '"\'=EXEMPLO(""teste"")' in text
    put = ui.locator('[data-grid-name="puts"]')
    put.locator(".grid-profile").select_option("essential")
    put.locator('[data-format="text"]').click()
    text = put.locator("textarea").input_value()
    assert "Cotações de opções: 2026-10-07" in text and "Vencimento: 16/10/2026" in text
    assert "Fonte: ultimo" in text and "Execucao: Acompanha book" in text


def test_custom_columns_and_fresh_htmx_swap(ui):
    fund = ui.locator('[data-grid-name="indicadores"]')
    fund.locator(".grid-column-picker summary").click()
    fund.locator('.grid-column-toggle[data-key="pl"]').uncheck()
    assert fund.locator(".grid-profile").input_value() == "custom"
    assert fund.locator('tbody tr:first-child td[data-key="pl"]').is_hidden()
    assert fund.locator('.grid-column-toggle[data-key="papel"]').is_disabled()
    fund.locator(".grid-select-all").check()
    fund.locator('.column-filter[data-key="cotacao"]').fill("=0")
    ui.evaluate(
        """html => {
          const dashboard = document.getElementById('fundamentus-dashboard');
          dashboard.innerHTML = html;
          dashboard.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles:true}));
        }""",
        ui.fundamentus_partial,
    )
    assert _rows(fund) == ["PETR4", "VALE3", "WEGE3", "BBAS3"]
    assert fund.locator(".grid-profile").input_value() == "custom"
    assert not fund.locator(".grid-select-all").is_checked()
    assert fund.locator('.column-filter[data-key="cotacao"]').input_value() == ""
    fund.locator('button[data-key="cotacao"]').click()
    assert _rows(fund) == ["VALE3", "PETR4", "BBAS3", "WEGE3"]


@pytest.mark.parametrize("width", [375, 1366, 1920, 3440])
def test_layout_overflow_and_sticky_columns(ui, width):
    ui.set_viewport_size({"width": width, "height": 1000})
    ui.wait_for_timeout(100)
    assert ui.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert (
        ui.locator("main").evaluate("el => el.getBoundingClientRect().width")
        > width * 0.9
    )
    fund = ui.locator('[data-grid-name="indicadores"]')
    wrap = fund.locator(".fundamentus-table-wrap")
    wrap.evaluate("el => {el.scrollLeft = 500; el.scrollTop = 100;}")
    first_cell = fund.locator('tbody tr:first-child td[data-key="papel"]')
    offset = first_cell.bounding_box()["x"] - wrap.bounding_box()["x"]
    assert 40 <= offset <= 55
    ui.evaluate("document.body.style.zoom = '2'")
    ui.wait_for_timeout(100)
    assert ui.evaluate(
        "document.documentElement.scrollWidth <= innerWidth"
    ), ui.evaluate(
        """() => ({inner:innerWidth, scroll:document.documentElement.scrollWidth,
        client:document.documentElement.clientWidth, body:document.body.getBoundingClientRect().toJSON(),
        elements:[...document.querySelectorAll('body *')]
        .filter(el => (!el.closest('.fundamentus-table-wrap') || el.matches('.fundamentus-table-wrap')) && el.getBoundingClientRect().right > innerWidth)
        .map(el => [el.tagName, el.className, el.getBoundingClientRect().toJSON()]).slice(0,10)})"""
    )
