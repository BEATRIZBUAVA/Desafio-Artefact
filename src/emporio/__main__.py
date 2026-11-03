"""CLI de chat com a assistente da Empório da Música.

Uso:
    python -m emporio                  # nova conversa
    python -m emporio --sessao maria   # retoma (ou cria) a conversa "maria"
    python -m emporio --debug          # mostra as ferramentas chamadas

Comandos durante o chat: /sair, /limpar, /debug
"""

from __future__ import annotations

import argparse
import sys
import uuid

from .agent import Agente, formatar_chamada
from .prompt import PERSONA

CINZA, VERDE, RESET = "\033[90m", "\033[32m", "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat com a assistente da Empório da Música")
    parser.add_argument("--sessao", default=None, help="id da conversa (para retomar depois)")
    parser.add_argument("--debug", action="store_true", help="mostra as chamadas de ferramenta")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    sessao = args.sessao or uuid.uuid4().hex[:8]
    debug = args.debug
    agente = Agente(sessao)

    retomada = bool(agente.historico.carregar())
    print(f"Empório da Música — conversa '{sessao}'{' (retomada)' if retomada else ''}")
    print("Comandos: /sair, /limpar, /debug\n")

    while True:
        try:
            msg = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg == "/sair":
            break
        if msg == "/limpar":
            agente.historico.limpar()
            print("Histórico apagado.\n")
            continue
        if msg == "/debug":
            debug = not debug
            print(f"Debug {'ligado' if debug else 'desligado'}.\n")
            continue

        resposta = agente.responder(msg)
        if debug:
            for c in resposta.chamadas:
                print(f"{CINZA}  ↳ {formatar_chamada(c)}{RESET}")
        print(f"{VERDE}{PERSONA}:{RESET} {resposta.texto}\n")

    print(f"Até mais! Para retomar: python -m emporio --sessao {sessao}")


if __name__ == "__main__":
    main()
