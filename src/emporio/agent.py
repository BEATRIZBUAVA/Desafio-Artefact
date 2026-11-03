"""Loop do agente: Gemini + function calling manual.

Fazemos o loop de ferramentas à mão (em vez do function calling automático do
SDK) para: registrar cada chamada (debug e conversas de exemplo), limitar o
número de rodadas e persistir o histórico completo, incluindo as respostas
das ferramentas.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from . import prompt, tools
from .memory import Historico

load_dotenv()

MODELO_PADRAO = "gemini-3.6-flash"
FALLBACKS_PADRAO = "gemini-3.5-flash,gemini-3.8-flash"
MAX_RODADAS_FERRAMENTA = 6


@dataclass
class ChamadaFerramenta:
    nome: str
    argumentos: dict
    resultado: dict


@dataclass
class Resposta:
    texto: str
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)


class Agente:
    def __init__(self, sessao: str, modelo: str | None = None, historico: Historico | None = None):
        chave = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not chave:
            raise RuntimeError("Defina GEMINI_API_KEY no arquivo .env (veja .env.example).")
        self.cliente = genai.Client(api_key=chave)
        self.modelo = modelo or os.getenv("GEMINI_MODEL", MODELO_PADRAO)
        self.fallbacks = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", FALLBACKS_PADRAO).split(",") if m.strip()]
        self.historico = historico or Historico(sessao)
        self.ferramentas = [
            types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in tools.DECLARACOES])
        ]

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=prompt.montar(),
            tools=self.ferramentas,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _gerar(self, conteudos: list[types.Content]) -> types.GenerateContentResponse:
        # O plano gratuito tem limite baixo de requisições por minuto e os
        # modelos às vezes ficam sobrecarregados (503). Tentamos de novo com
        # espera crescente e, se o modelo continuar indisponível, passamos para
        # o próximo da lista de fallback e ficamos nele pelo resto da sessão.
        candidatos = [self.modelo] + [m for m in self.fallbacks if m != self.modelo]
        for i, modelo in enumerate(candidatos):
            espera = 3
            for tentativa in range(3):
                try:
                    resposta = self.cliente.models.generate_content(
                        model=modelo, contents=conteudos, config=self._config()
                    )
                    self.modelo = modelo
                    return resposta
                except (errors.ClientError, errors.ServerError) as exc:
                    codigo = getattr(exc, "code", None)
                    if codigo not in (429, 500, 503) or (tentativa == 2 and i == len(candidatos) - 1):
                        raise
                    if tentativa == 2:
                        break
                    time.sleep(espera)
                    espera *= 2
        raise RuntimeError("inalcançável")

    def responder(self, mensagem: str) -> Resposta:
        conversa = self.historico.carregar()
        novos = [types.Content(role="user", parts=[types.Part.from_text(text=mensagem)])]
        chamadas: list[ChamadaFerramenta] = []

        for _ in range(MAX_RODADAS_FERRAMENTA):
            resposta = self._gerar(conversa + novos)
            candidato = resposta.candidates[0].content if resposta.candidates else None
            if candidato is None:
                break
            novos.append(candidato)
            if not resposta.function_calls:
                break

            partes = []
            for fc in resposta.function_calls:
                args = dict(fc.args or {})
                resultado = tools.executar(fc.name, args)
                chamadas.append(ChamadaFerramenta(fc.name, args, resultado))
                partes.append(types.Part.from_function_response(name=fc.name, response={"resultado": resultado}))
            novos.append(types.Content(role="user", parts=partes))

        texto = _texto(novos[-1]) if novos[-1].role == "model" else ""
        if not texto:
            texto = (
                "Opa, me enrolei aqui pra encontrar essa informação 😅 Pode reformular? "
                "Se preferir, falo com alguém da equipe pra te ajudar."
            )
            novos.append(types.Content(role="model", parts=[types.Part.from_text(text=texto)]))
        self.historico.adicionar(novos)
        return Resposta(texto=texto, chamadas=chamadas)


def _texto(conteudo: types.Content) -> str:
    return "".join(p.text for p in conteudo.parts or [] if p.text and not p.thought).strip()


def formatar_chamada(c: ChamadaFerramenta, limite: int = 300) -> str:
    args = json.dumps(c.argumentos, ensure_ascii=False)
    res = json.dumps(c.resultado, ensure_ascii=False, default=str)
    if len(res) > limite:
        res = res[:limite] + "…"
    return f"{c.nome}({args}) -> {res}"
