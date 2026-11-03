"""Relógio da loja (fuso de Campo Grande) e calendário de funcionamento.

A variável de ambiente EMPORIO_AGORA (ISO, ex.: 2026-11-03T10:30) fixa o
"agora" — usada nos testes e para gerar as conversas de exemplo de forma
reproduzível.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Campo_Grande")

# (abre, fecha) por weekday(): 0 = segunda ... 6 = domingo
EXPEDIENTE = {d: (time(9), time(18)) for d in range(5)} | {5: (time(9), time(13))}

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def agora() -> datetime:
    fixo = os.getenv("EMPORIO_AGORA")
    if fixo:
        return datetime.fromisoformat(fixo).replace(tzinfo=FUSO)
    return datetime.now(FUSO)


def _pascoa(ano: int) -> date:
    # Algoritmo de Meeus/Jones/Butcher
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriados(ano: int) -> dict[date, str]:
    fixos = {
        (1, 1): "Confraternização Universal",
        (4, 21): "Tiradentes",
        (5, 1): "Dia do Trabalho",
        (8, 26): "Aniversário de Campo Grande",
        (9, 7): "Independência",
        (10, 11): "Criação do Estado de MS",
        (10, 12): "Nossa Senhora Aparecida",
        (11, 2): "Finados",
        (11, 15): "Proclamação da República",
        (11, 20): "Consciência Negra",
        (12, 25): "Natal",
    }
    dias = {date(ano, m, d): nome for (m, d), nome in fixos.items()}
    pascoa = _pascoa(ano)
    dias[pascoa - timedelta(days=2)] = "Sexta-feira Santa"
    dias[pascoa + timedelta(days=60)] = "Corpus Christi"
    return dias


def situacao_loja(momento: datetime | None = None) -> dict:
    momento = momento or agora()
    hoje = momento.date()
    feriado = feriados(hoje.year).get(hoje)
    janela = None if feriado else EXPEDIENTE.get(hoje.weekday())
    aberta = bool(janela and janela[0] <= momento.time() < janela[1])

    proxima = None
    if not aberta:
        for delta in range(0, 8):
            dia = hoje + timedelta(days=delta)
            jan = None if feriados(dia.year).get(dia) else EXPEDIENTE.get(dia.weekday())
            if jan and (delta > 0 or momento.time() < jan[0]):
                proxima = f"{DIAS[dia.weekday()]} {dia.strftime('%d/%m')} às {jan[0].strftime('%H:%M')}"
                break

    return {
        "agora": momento.strftime("%d/%m/%Y %H:%M"),
        "dia_da_semana": DIAS[momento.weekday()],
        "feriado_hoje": feriado,
        "aberta_agora": aberta,
        "fecha_hoje_as": janela[1].strftime("%H:%M") if aberta else None,
        "proxima_abertura": proxima,
    }
