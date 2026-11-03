"""Recuperação das políticas da loja por tópico.

O manual tem 8 páginas e 9 seções bem delimitadas. Em vez de embeddings e
busca vetorial, cada seção `##` de data/politicas.md é um "documento" e o
modelo escolhe o tópico por um enum na declaração da ferramenta. Com esse
tamanho de corpus a escolha por tópico é determinística, auditável e não
erra por similaridade semântica fraca (ver README, "Retrieval").
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

POLITICAS_MD = Path(__file__).resolve().parents[2] / "data" / "politicas.md"

DESCRICAO_TOPICOS = {
    "sobre": "quem é a loja, o que vende (só instrumentos), endereço, telefone, WhatsApp, e-mail, CNPJ",
    "horario": "horário de funcionamento da loja e do WhatsApp, domingos e feriados",
    "pagamento": "formas de pagamento, desconto no PIX, parcelamento e parcela mínima, boleto",
    "trocas_devolucoes": "arrependimento, devolução, troca por defeito ou por preferência, itens não trocáveis",
    "frete_entregas": "frete, prazos de entrega, Correios/Jadlog, motoboy, rastreamento, avaria",
    "promocoes": "campanhas do ano (Black Friday etc.) e regras de promoção",
    "atendimento": "diretrizes de atendimento, escopo, produto esgotado/descontinuado, reclamações",
    "garantia": "garantia legal e do fabricante, o que a garantia não cobre",
    "privacidade": "LGPD, uso e exclusão de dados pessoais",
}


@lru_cache(maxsize=1)
def carregar_secoes(caminho: Path = POLITICAS_MD) -> dict[str, str]:
    secoes: dict[str, str] = {}
    atual = None
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith("## "):
            atual = linha[3:].strip()
            secoes[atual] = ""
        elif atual:
            secoes[atual] += linha + "\n"
    return {k: v.strip() for k, v in secoes.items()}


def consultar(topico: str) -> dict:
    secoes = carregar_secoes()
    if topico not in secoes:
        return {"erro": f"tópico desconhecido: {topico}", "topicos_validos": sorted(secoes)}
    return {"topico": topico, "texto": secoes[topico]}
