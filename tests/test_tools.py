"""Testes das ferramentas (sem LLM): garantem que os dados que o agente
recebe estão corretos, independentemente do modelo."""

from datetime import datetime

import pytest

from emporio import clock, tools


@pytest.fixture(autouse=True)
def agora_fixo(monkeypatch):
    monkeypatch.setenv("EMPORIO_AGORA", "2026-11-03T10:30")


def test_busca_por_modelo_exato():
    r = tools.buscar_produtos(termo="Takamine GD20")["resultados"]
    assert [p["id"] for p in r] == [95]
    assert r[0]["preco_tabela"] == 2199.0
    assert r[0]["preco_pix"] == pytest.approx(2089.05)


def test_violoes_ate_mil_so_disponiveis():
    r = tools.buscar_produtos(categoria="Violões", preco_max=1000)["resultados"]
    assert r and all(p["categoria"] == "Violões" and p["disponivel"] for p in r)
    assert 96 not in [p["id"] for p in r]  # ativo, mas estoque 0
    assert 113 not in [p["id"] for p in r]  # descontinuado


def test_produto_esgotado_sugere_alternativas():
    r = tools.buscar_produtos(termo="Giannini GF-3D")
    assert r["resultados"] == []
    assert r["encontrados_indisponiveis"][0]["estoque"] == 0
    assert r["alternativas_disponiveis"]


def test_promocao_ativa_e_pix_nao_acumula():
    p = tools.detalhes_produto(121)  # Ohana CK-20, 20% ativo
    assert p["promocao_ativa"]["desconto_pct"] == 20
    assert p["promocao_ativa"]["preco_promocional"] == pytest.approx(439.2)
    assert "preco_pix" not in p


def test_promocao_expirada_nao_aparece():
    p = tools.detalhes_produto(95)  # GD20 teve "Oferta Especial" inativa
    assert "promocao_ativa" not in p


def test_descontinuado_com_estoque_nao_e_vendido():
    p = tools.detalhes_produto(136)
    assert p["status"] == "descontinuado" and p["disponivel"] is False


def test_parcelamento_respeita_minimos():
    assert tools.simular_pagamento(600)["credito_max_parcelas_sem_juros"]["parcelas"] == 6  # 7x < R$100
    assert tools.simular_pagamento(700)["credito_max_parcelas_sem_juros"]["parcelas"] == 7
    assert tools.simular_pagamento(400)["credito_max_parcelas_sem_juros"]["parcelas"] == 5
    assert tools.simular_pagamento(120)["credito_max_parcelas_sem_juros"]["parcelas"] == 2
    assert tools.simular_pagamento(5000)["credito_max_parcelas_sem_juros"]["parcelas"] == 12


def test_pedido_exige_cliente_dono():
    assert "erro" in tools.consultar_pedido(1, "lucas.mendes@jmail.com")  # pedido 1 é do cliente 3
    ok = tools.consultar_pedido(1, "(67) 98432-1098")
    assert ok["pedido"] == 1 and ok["status"] == "entregue"


def test_pedido_entregue_fora_do_prazo_de_arrependimento():
    prazos = tools.consultar_pedido(7, "14")  # telefone curto demais não identifica
    assert "erro" in prazos
    cliente14 = tools.store().clientes.loc[14, "email"]
    prazos = tools.consultar_pedido(7, cliente14)["prazos_pos_venda"]
    assert prazos["arrependimento_7_dias_do_recebimento"]["dentro_do_prazo"] is False
    assert prazos["garantia_legal_90_dias_do_recebimento"]["dentro_do_prazo"] is False


def test_politica_por_topico():
    assert "7 dias" in tools.consultar_politicas("trocas_devolucoes")["texto"]
    assert "erro" in tools.consultar_politicas("inexistente")


def test_horario_loja():
    terca_manha = clock.situacao_loja(datetime(2026, 11, 3, 10, 0, tzinfo=clock.FUSO))
    assert terca_manha["aberta_agora"] is True
    sabado_tarde = clock.situacao_loja(datetime(2026, 11, 7, 14, 0, tzinfo=clock.FUSO))
    assert sabado_tarde["aberta_agora"] is False
    assert sabado_tarde["proxima_abertura"].startswith("segunda-feira 09/11")
    finados = clock.situacao_loja(datetime(2026, 11, 2, 10, 0, tzinfo=clock.FUSO))
    assert finados["feriado_hoje"] == "Finados" and finados["aberta_agora"] is False


def test_descricao_de_outra_marca_e_omitida():
    p = tools.detalhes_produto(144)  # "Roland" com descrição de Yamaha
    assert p["descricao"] is None and "obs_cadastro" in p
    assert tools.detalhes_produto(95)["descricao"]


def test_pedido_enviado_atrasado_gera_alerta():
    p = tools.consultar_pedido(8, "(67) 99654-7821")
    assert p["status"] == "enviado" and "atrasada" in p["alerta"]


def test_busca_avisa_quando_ha_mais_resultados():
    r = tools.buscar_produtos(categoria="Violões", preco_max=1000)
    assert len(r["resultados"]) == 10 and r["total_encontrado"] == 12
