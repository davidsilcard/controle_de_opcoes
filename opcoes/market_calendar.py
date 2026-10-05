"""Calendário explícito: não confundir vencimentos mensais com semanais.

Escopo inicial: Fundamentus. Atualizar datas/horários com revisão e testes,
nunca inferir feriados ou usar a data do snapshot como relógio de negociação.
"""

import datetime as dt

# B3, calendário de opções sobre ações, consultado em 05/10/2026.
CALENDAR_SOURCE = (
    "https://www.b3.com.br/main.jsp?doui_processActionId=setLocaleProcessAction"
    "&locale=pt_BR&lumA=1&lumII=8A80CB81633FBF0B016340EBEC880DCF"
    "&lumPageId=8A6882694E91F2D4014E92D6BA5C158F"
)
SESSION_SOURCE = (
    "https://www.b3.com.br/data/files/E3/B2/C2/12/BC09C910F37907C9AC094EA8/"
    "OC%20005-2026%20PRE%20NOVOS%20HORARIOS%20DE%20NEGOCIACAO_PT.pdf"
)
VERIFIED_ON = dt.date(2026, 10, 5)
VALID_FROM = dt.date(2026, 4, 1)
# A validade acaba na última sessão coberta, não extrapola o ano seguinte.
EXPIRY_CLOSE = dt.time(15, 45)  # Ofício 005/2026-PRE, anexo 3/4, séries vincendas.
SAO_PAULO = dt.timezone(dt.timedelta(hours=-3), name="America/Sao_Paulo")
MONTHLY_EXPIRIES = tuple(
    dt.date.fromisoformat(value)
    for value in (
        "2026-04-17",
        "2026-05-15",
        "2026-06-19",
        "2026-07-17",
        "2026-08-21",
        "2026-09-18",
        "2026-10-16",
        "2026-11-19",
        "2026-12-18",
        "2027-01-15",
        "2027-02-19",
        "2027-03-19",
        "2027-04-16",
        "2027-05-21",
        "2027-06-18",
        "2027-07-16",
        "2027-08-20",
        "2027-09-17",
        "2027-10-15",
        "2027-11-19",
        "2027-12-17",
    )
)


def market_now() -> dt.datetime:
    return dt.datetime.now(SAO_PAULO)


def next_monthly_expiry(now: dt.datetime) -> dt.date | None:
    """Próxima série mensal negociável; None exige calendário atualizado.

    Recebe instante consciente de fuso. São Paulo permanece UTC-3 na cobertura
    publicada; mudança legal de fuso exige revisão desta versão do calendário.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("O relógio do mercado precisa informar o fuso horário.")
    local = now.astimezone(SAO_PAULO)
    if local.date() < VALID_FROM:
        return None
    for expiry in MONTHLY_EXPIRIES:
        if local < dt.datetime.combine(expiry, EXPIRY_CLOSE, SAO_PAULO):
            return expiry
    return None
