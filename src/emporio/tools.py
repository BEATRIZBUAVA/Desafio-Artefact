"""Ferramentas expostas ao LLM via function calling.

Cada ferramenta é uma função Python determinística que devolve um dict
serializável em JSON. As declarações (nome, descrição, JSON Schema) ficam em
DECLARACOES; é por elas que o modelo decide QUANDO consultar dados e QUANDO
consultar políticas.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, timedelta
from pathlib import Path

from . import clock, policies
from .data import Store

SOLICITACOES = Path(__file__).resolve().parents[2] / "data" / "solicitacoes.jsonl"

MAX_RESULTADOS = 10

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


# ------------------------------------------------------------------ catálogo


def buscar_produtos(
    termo: str | None = None,
    categoria: str | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    incluir_indisponiveis: bool = False,
) -> dict:
    s = store()
    todos = s.buscar_produtos(termo, categoria, preco_min, preco_max, incluir_indisponiveis, limite=1000)
    resultados = todos[:MAX_RESULTADOS]
    resposta: dict = {"resultados": resultados}
    if len(todos) > len(resultados):
        resposta["total_encontrado"] = len(todos)
        resposta["obs"] = (
            f"Mostrando os {len(resultados)} mais baratos de {len(todos)}. "
            "Diga ao cliente que há mais opções e ofereça refinar (faixa de preço, nylon/aço, marca)."
        )
    if resultados or incluir_indisponiveis:
        return resposta

    # Nada disponível: verifica se o produto existe mas está esgotado/descontinuado,
    # para o agente não dizer "não temos" quando na verdade "acabou".
    indisponiveis = s.buscar_produtos(termo, categoria, preco_min, preco_max, incluir_indisponiveis=True)
    if indisponiveis:
        resposta["encontrados_indisponiveis"] = indisponiveis
        cat = indisponiveis[0]["categoria"]
        ref = indisponiveis[0]["preco_tabela"]
        resposta["alternativas_disponiveis"] = s.buscar_produtos(
            categoria=cat, preco_min=ref * 0.6, preco_max=ref * 1.4, limite=4
        )
    else:
        resposta["aviso"] = "Nenhum instrumento encontrado com esses critérios no catálogo."
    return resposta


def detalhes_produto(produto_id: int) -> dict:
    ficha = store().produto(int(produto_id))
    return ficha or {"erro": f"produto {produto_id} não encontrado"}


def simular_pagamento(valor: float, preco_promocional: bool = False) -> dict:
    """Aplica as regras da seção 3 do manual a um valor de compra."""
    valor = float(valor)
    opcoes = []
    for n in range(1, 13):
        minimo = 50 if n <= 3 else 80 if n <= 6 else 100
        parcela = valor / n
        if n == 1 or parcela >= minimo:
            opcoes.append({"parcelas": n, "valor_parcela": math.floor(parcela * 100) / 100})
    return {
        "valor": round(valor, 2),
        "pix": round(valor, 2) if preco_promocional else round(valor * 0.95, 2),
        "pix_obs": "sem desconto extra: preço já promocional" if preco_promocional else "5% de desconto",
        "debito_ou_boleto": round(valor, 2),
        "credito_max_parcelas_sem_juros": opcoes[-1],
        "pode_combinar_formas": valor > 2000,
    }


# ------------------------------------------------------------------- pedidos


def _prazos(pedido: dict, hoje: date) -> dict:
    """Janelas de troca/devolução/garantia (seções 4 e 8) para um pedido entregue.

    O CSV não tem a data real de recebimento; usamos a previsão de entrega
    como aproximação (suposição documentada no README).
    """
    compra = date.fromisoformat(pedido["data_compra"])
    receb = date.fromisoformat(pedido["previsao_entrega"])

    def janela(fim: date) -> dict:
        return {"ate": fim.isoformat(), "dentro_do_prazo": hoje <= fim, "dias_restantes": max((fim - hoje).days, 0)}

    return {
        "data_recebimento_considerada": receb.isoformat(),
        "hoje": hoje.isoformat(),
        "arrependimento_7_dias_do_recebimento": janela(receb + timedelta(days=7)),
        "troca_por_preferencia_7_dias": janela(receb + timedelta(days=7)),
        "troca_por_defeito_30_dias_da_compra": janela(compra + timedelta(days=30)),
        "garantia_legal_90_dias_do_recebimento": janela(receb + timedelta(days=90)),
        "obs": "Fora dos prazos da loja, defeitos seguem pela garantia do fabricante (6 meses a 2 anos); a loja pode intermediar.",
    }


def consultar_pedido(numero_pedido: int, email_ou_telefone: str) -> dict:
    s = store()
    numero_pedido = int(numero_pedido)
    cliente = s.identificar_cliente(email_ou_telefone)
    # Mesma mensagem para "pedido não existe" e "pedido de outra pessoa":
    # não confirmamos a existência de pedidos de terceiros (LGPD).
    negado = {"erro": "Não encontrei esse pedido para o e-mail/telefone informado. Confira os dados."}
    if cliente is None or numero_pedido not in s.pedidos.index:
        return negado
    if s.pedidos.loc[numero_pedido, "customer_id"] != cliente["customer_id"]:
        return negado

    pedido = s.resumo_pedido(numero_pedido)
    pedido["cliente"] = cliente["name"].split()[0]
    hoje = clock.agora().date()
    if pedido["status_codigo"] == "delivered" and pedido["previsao_entrega"]:
        pedido["prazos_pos_venda"] = _prazos(pedido, hoje)
    elif pedido["status_codigo"] == "shipped" and pedido["previsao_entrega"]:
        atraso = (hoje - date.fromisoformat(pedido["previsao_entrega"])).days
        if atraso > 0:
            pedido["alerta"] = f"Entrega atrasada há {atraso} dias em relação à previsão: ofereça abrir um chamado com a equipe."
    return pedido


def listar_pedidos_cliente(email_ou_telefone: str) -> dict:
    s = store()
    cliente = s.identificar_cliente(email_ou_telefone)
    if cliente is None:
        return {"erro": "Não encontrei cadastro com esse e-mail/telefone."}
    # O cliente já foi identificado pelo contato, então devolvemos o detalhe
    # completo de cada pedido (rastreio, prazos, alerta de atraso).
    contato = email_ou_telefone
    pedidos = [consultar_pedido(i, contato) for i in s.pedidos_do_cliente(int(cliente["customer_id"]))]
    return {"cliente": cliente["name"].split()[0], "pedidos": pedidos}


# --------------------------------------------------------------- loja/geral


def info_loja() -> dict:
    return {
        "nome": "Empório da Música",
        "endereco": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
        "telefone": "(67) 3341-4444",
        "whatsapp": "(67) 3321-4500",
        "email": "contato@emporiodamusica.com.br",
        "horarios": "Seg a sex 09:00–18:00; sáb 09:00–13:00; domingos e feriados fechado",
        "situacao_agora": clock.situacao_loja(),
    }


def consultar_politicas(topico: str) -> dict:
    return policies.consultar(topico)


def registrar_solicitacao(tipo: str, resumo: str, contato: str, numero_pedido: int | None = None) -> dict:
    """Registra reclamação ou pedido de atendimento humano para a equipe."""
    protocolo = uuid.uuid4().hex[:8].upper()
    registro = {
        "protocolo": protocolo,
        "tipo": tipo,
        "resumo": resumo,
        "contato": contato,
        "numero_pedido": numero_pedido,
        "registrado_em": clock.agora().isoformat(timespec="minutes"),
    }
    SOLICITACOES.parent.mkdir(parents=True, exist_ok=True)
    with SOLICITACOES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {"protocolo": protocolo, "prazo_retorno": "até 24 horas úteis", "registrado": True}


# -------------------------------------------------------------- declarações

FUNCOES = {
    f.__name__: f
    for f in (
        buscar_produtos,
        detalhes_produto,
        simular_pagamento,
        consultar_pedido,
        listar_pedidos_cliente,
        info_loja,
        consultar_politicas,
        registrar_solicitacao,
    )
}

_CATEGORIAS = [
    "Guitarras",
    "Baixos",
    "Baterias e Percussão",
    "Teclados e Pianos",
    "Violões",
    "Instrumentos de Sopro (Madeiras)",
    "Instrumentos de Sopro (Metais)",
    "Cordas Orquestrais",
    "Ukuleles",
]

DECLARACOES = [
    {
        "name": "buscar_produtos",
        "description": (
            "Busca instrumentos no catálogo em tempo real: preço de tabela, preço no PIX, promoção ativa, "
            "estoque e disponibilidade. Use SEMPRE antes de falar de preço, estoque ou opções de produto. "
            "Por padrão traz só itens disponíveis; se não houver, informa itens esgotados/descontinuados "
            "que batem com a busca e alternativas parecidas."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string", "description": "Marca, modelo ou palavras do nome. Ex.: 'Takamine GD20', 'Yamaha', 'nylon'."},
                "categoria": {"type": "string", "enum": _CATEGORIAS},
                "preco_min": {"type": "number", "description": "Preço mínimo em reais."},
                "preco_max": {"type": "number", "description": "Preço máximo em reais (considera o preço promocional, se houver)."},
                "incluir_indisponiveis": {"type": "boolean", "description": "Inclui esgotados, descontinuados e 'em breve'."},
            },
        },
    },
    {
        "name": "detalhes_produto",
        "description": "Descrição completa e especificações técnicas (madeiras, cordas, eletrônica etc.) de um produto pelo id.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"produto_id": {"type": "integer"}},
            "required": ["produto_id"],
        },
    },
    {
        "name": "simular_pagamento",
        "description": (
            "Calcula valor no PIX e o parcelamento máximo sem juros permitido para um valor, segundo as regras "
            "da loja. Use quando o cliente perguntar 'em quantas vezes', 'quanto fica no PIX' etc."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "valor": {"type": "number", "description": "Valor da compra em reais (use o preço promocional se houver)."},
                "preco_promocional": {"type": "boolean", "description": "true se o valor já é preço de promoção (PIX não dá desconto extra)."},
            },
            "required": ["valor"],
        },
    },
    {
        "name": "consultar_pedido",
        "description": (
            "Status, itens, rastreio e previsão de um pedido, mais os prazos de troca/devolução/garantia já "
            "calculados para hoje. Exige número do pedido E e-mail ou telefone do cadastro (verificação de "
            "identidade). Peça esses dados ao cliente antes de chamar; nunca invente."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "numero_pedido": {"type": "integer"},
                "email_ou_telefone": {"type": "string"},
            },
            "required": ["numero_pedido", "email_ou_telefone"],
        },
    },
    {
        "name": "listar_pedidos_cliente",
        "description": "Lista os pedidos de um cliente a partir do e-mail ou telefone do cadastro, para quando ele não sabe o número do pedido.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"email_ou_telefone": {"type": "string"}},
            "required": ["email_ou_telefone"],
        },
    },
    {
        "name": "info_loja",
        "description": "Endereço, telefone, WhatsApp, e-mail, horários e se a loja está aberta AGORA (data/hora atual e próxima abertura).",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "consultar_politicas",
        "description": (
            "Lê o trecho do manual oficial de políticas da loja sobre um tópico. Use para regras: trocas, "
            "devoluções, garantia, frete, pagamento, promoções, privacidade, escopo de atendimento. "
            "Tópicos: " + "; ".join(f"{k} = {v}" for k, v in policies.DESCRICAO_TOPICOS.items())
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {"topico": {"type": "string", "enum": list(policies.DESCRICAO_TOPICOS)}},
            "required": ["topico"],
        },
    },
    {
        "name": "registrar_solicitacao",
        "description": (
            "Registra uma reclamação ou um pedido de atendimento humano (casos que fogem das regras, cancelamento, "
            "negociação, dúvida que a política não resolve) e devolve um protocolo. Só chame depois de ter um "
            "contato do cliente e um resumo claro do caso."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["reclamacao", "atendimento_humano"]},
                "resumo": {"type": "string"},
                "contato": {"type": "string", "description": "Telefone ou e-mail para retorno."},
                "numero_pedido": {"type": "integer"},
            },
            "required": ["tipo", "resumo", "contato"],
        },
    },
]


def executar(nome: str, argumentos: dict) -> dict:
    funcao = FUNCOES.get(nome)
    if funcao is None:
        return {"erro": f"ferramenta desconhecida: {nome}"}
    try:
        return funcao(**argumentos)
    except Exception as exc:  # o erro volta ao modelo, que pode se corrigir
        return {"erro": f"{type(exc).__name__}: {exc}"}
