"""Histórico de conversa persistido em SQLite, por sessão.

Guardamos cada `types.Content` (mensagens do cliente, respostas do modelo,
chamadas e respostas de ferramenta) serializado em JSON. Assim o cliente pode
fechar a CLI e retomar a conversa com o mesmo id, como num chat de WhatsApp.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from google.genai import types

DB_PADRAO = Path(__file__).resolve().parents[2] / "data" / "conversas.db"


class Historico:
    def __init__(self, sessao: str, caminho: Path = DB_PADRAO):
        self.sessao = sessao
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho)
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessao TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )

    def carregar(self, max_turnos: int = 20) -> list[types.Content]:
        linhas = self.con.execute(
            "SELECT conteudo FROM mensagens WHERE sessao = ? ORDER BY id", (self.sessao,)
        ).fetchall()
        conteudos = [types.Content.model_validate_json(c) for (c,) in linhas]
        return janela(conteudos, max_turnos)

    def adicionar(self, conteudos: list[types.Content]) -> None:
        self.con.executemany(
            "INSERT INTO mensagens (sessao, conteudo) VALUES (?, ?)",
            [(self.sessao, c.model_dump_json(exclude_none=True)) for c in conteudos],
        )
        self.con.commit()

    def limpar(self) -> None:
        self.con.execute("DELETE FROM mensagens WHERE sessao = ?", (self.sessao,))
        self.con.commit()


def _e_texto_do_cliente(c: types.Content) -> bool:
    return c.role == "user" and any(p.text for p in c.parts or [])


def janela(conteudos: list[types.Content], max_turnos: int) -> list[types.Content]:
    """Mantém os últimos `max_turnos` turnos do cliente, sempre começando numa
    mensagem de texto do cliente (nunca no meio de uma chamada de ferramenta,
    o que a API rejeita)."""
    inicios = [i for i, c in enumerate(conteudos) if _e_texto_do_cliente(c)]
    if len(inicios) <= max_turnos:
        return conteudos
    return conteudos[inicios[-max_turnos]:]
