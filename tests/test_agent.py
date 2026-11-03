"""Testa o loop do agente com um cliente Gemini falso (sem rede):
chamada de ferramenta -> resposta final -> histórico persistido e retomado."""

from google.genai import types

from emporio.agent import Agente
from emporio.memory import Historico


class ModelsFalso:
    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebidos = []

    def generate_content(self, model, contents, config):
        self.recebidos.append(list(contents))
        return self.roteiro.pop(0)


def _resposta(*partes):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(partes)))]
    )


def _agente(tmp_path, monkeypatch, roteiro):
    monkeypatch.setenv("GEMINI_API_KEY", "teste")
    agente = Agente("t1", historico=Historico("t1", tmp_path / "c.db"))
    falso = ModelsFalso(roteiro)
    agente.cliente = type("C", (), {"models": falso})()
    return agente, falso


def test_loop_chama_ferramenta_e_persiste(tmp_path, monkeypatch):
    agente, falso = _agente(
        tmp_path,
        monkeypatch,
        [
            _resposta(types.Part.from_function_call(name="buscar_produtos", args={"termo": "Takamine GD20"})),
            _resposta(types.Part.from_text(text="O GD20 sai por R$ 2.199,00.")),
        ],
    )
    r = agente.responder("Quanto custa o Takamine GD20?")

    assert r.texto == "O GD20 sai por R$ 2.199,00."
    assert r.chamadas[0].nome == "buscar_produtos"
    assert r.chamadas[0].resultado["resultados"][0]["id"] == 95
    # a segunda chamada ao modelo recebeu a resposta da ferramenta
    assert falso.recebidos[1][-1].parts[0].function_response.name == "buscar_produtos"

    # histórico sobrevive a uma nova instância (retomada de sessão)
    retomado = Historico("t1", tmp_path / "c.db").carregar()
    assert [c.role for c in retomado] == ["user", "model", "user", "model"]


def test_resposta_vazia_vira_mensagem_de_fallback(tmp_path, monkeypatch):
    agente, _ = _agente(tmp_path, monkeypatch, [_resposta(types.Part.from_text(text=""))])
    assert "reformular" in agente.responder("oi").texto


def test_declaracoes_validas():
    from emporio import tools

    decl = [types.FunctionDeclaration(**d) for d in tools.DECLARACOES]
    assert {d.name for d in decl} == set(tools.FUNCOES)
