"""Carga e tratamento dos CSVs da loja.

Tudo é carregado uma vez em memória (65 produtos, 20 pedidos): um banco não
traria ganho nesse volume. As regras de negócio que dependem dos dados
(promoção ativa, disponibilidade, verificação de cliente) ficam aqui e não no
prompt, para o LLM nunca precisar "fazer conta" sobre preço ou estoque.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

STATUS_PRODUTO = {
    "active": "ativo",
    "discontinued": "descontinuado",
    "coming_soon": "em breve",
}

STATUS_PEDIDO = {
    "pending": "aguardando pagamento/processamento",
    "confirmed": "confirmado, em separação",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

FORMA_PAGAMENTO = {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação, para buscas tolerantes."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def _radical(token: str) -> str:
    """Stemming mínimo de plural em português (violões -> violao, baixos -> baixo)."""
    if token.endswith("oes") and len(token) > 4:
        return token[:-3] + "ao"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokens(texto: str) -> set[str]:
    return {_radical(t) for t in normalizar(texto).split()}


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto))


MARCAS = [
    "Yamaha", "Roland", "Korg", "Nord", "Ibanez", "Fender", "Gibson", "Pearl", "Music Man",
    "Takamine", "Taylor", "Martin", "Giannini", "Tagima", "Crafter", "Kala", "Ohana", "PRS",
]


def marcas_conflitantes(nome: str, descricao: str) -> tuple[set[str], set[str]] | None:
    """Detecta descrição que cita outra marca que não a do nome (ex.: produto
    'Roland Synth 3' com descrição de um Yamaha)."""
    no_nome = {m for m in MARCAS if m in nome}
    na_desc = {m for m in MARCAS if m in str(descricao)}
    if no_nome and na_desc and not no_nome & na_desc:
        return no_nome, na_desc
    return None


def descrever_pagamento(codigo: str) -> str:
    if codigo.startswith("credit_"):
        return f"cartão de crédito em {codigo.removeprefix('credit_')}"
    return FORMA_PAGAMENTO.get(codigo, codigo)


@dataclass
class Store:
    raw_dir: Path = RAW_DIR

    def _csv(self, nome: str) -> pd.DataFrame:
        return pd.read_csv(self.raw_dir / f"{nome}.csv", encoding="utf-8")

    @cached_property
    def categorias(self) -> pd.DataFrame:
        return self._csv("categories")

    @cached_property
    def promocoes_ativas(self) -> pd.DataFrame:
        promo = self._csv("promotions")
        promo = promo[promo["is_active"] == 1]
        # Se um produto tiver mais de uma promoção ativa, vale a maior
        # (promoções não são cumulativas, seção 6.2 do manual).
        return promo.sort_values("discount_percent", ascending=False).drop_duplicates("product_id")

    @cached_property
    def produtos(self) -> pd.DataFrame:
        df = self._csv("products")
        df["specs"] = df["specs"].apply(lambda s: json.loads(s) if isinstance(s, str) and s else {})
        df = df.merge(
            self.categorias[["category_id", "name"]].rename(columns={"name": "categoria"}),
            on="category_id",
            how="left",
        )
        df = df.merge(
            self.promocoes_ativas[["product_id", "discount_percent", "description"]].rename(
                columns={"discount_percent": "desconto_pct", "description": "promocao"}
            ),
            on="product_id",
            how="left",
        )
        # Disponível para venda = ativo E com estoque. Um produto descontinuado
        # com estoque (id 136) ou "em breve" (id 130) não é ofertado.
        df["disponivel"] = (df["status"] == "active") & (df["stock_quantity"] > 0)
        df["_tokens"] = (df["name"] + " " + df["categoria"]).apply(tokens)
        return df.set_index("product_id", drop=False)

    @cached_property
    def clientes(self) -> pd.DataFrame:
        df = self._csv("customers")
        df["email_norm"] = df["email"].str.strip().str.lower()
        df["fone_norm"] = df["phone"].apply(so_digitos)
        return df.set_index("customer_id", drop=False)

    @cached_property
    def pedidos(self) -> pd.DataFrame:
        df = self._csv("orders")
        for col in ("order_date", "estimated_delivery"):
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        df = df.astype(object).where(df.notna(), None)
        return df.set_index("order_id", drop=False)

    @cached_property
    def itens_pedido(self) -> pd.DataFrame:
        return self._csv("order_items")

    # ---------------------------------------------------------------- produtos

    def ficha_produto(self, row: pd.Series, detalhada: bool = False) -> dict:
        preco = float(row["price_brl"])
        ficha = {
            "id": int(row["product_id"]),
            "nome": row["name"],
            "categoria": row["categoria"],
            "preco_tabela": round(preco, 2),
            "status": STATUS_PRODUTO.get(row["status"], row["status"]),
        }
        if row["status"] == "active":
            ficha["estoque"] = int(row["stock_quantity"])
            ficha["disponivel"] = bool(row["disponivel"])
        else:
            ficha["disponivel"] = False
        if pd.notna(row["desconto_pct"]):
            pct = int(row["desconto_pct"])
            ficha["promocao_ativa"] = {
                "nome": row["promocao"],
                "desconto_pct": pct,
                "preco_promocional": round(preco * (1 - pct / 100), 2),
                "obs": "PIX não acumula com promoção",
            }
        else:
            ficha["preco_pix"] = round(preco * 0.95, 2)
        if detalhada:
            if marcas_conflitantes(row["name"], row["description"]):
                # Não repassamos ao cliente uma descrição que fala de outro produto.
                ficha["descricao"] = None
                ficha["obs_cadastro"] = "descrição do cadastro em revisão; use só nome e especificações"
            else:
                ficha["descricao"] = row["description"]
            ficha["especificacoes"] = row["specs"]
        return ficha

    def buscar_produtos(
        self,
        termo: str | None = None,
        categoria: str | None = None,
        preco_min: float | None = None,
        preco_max: float | None = None,
        incluir_indisponiveis: bool = False,
        limite: int = 10,
    ) -> list[dict]:
        df = self.produtos
        if categoria:
            alvo = tokens(categoria)
            df = df[df["categoria"].apply(lambda c: bool(alvo & tokens(c)))]
        if termo:
            consulta = tokens(termo)
            score = df["_tokens"].apply(lambda t: len(consulta & t) / len(consulta))
            if score.empty or score.max() < 0.5:
                return []
            # Fica só com os mais aderentes, e ANTES de filtrar disponibilidade:
            # "Takamine GD20" traz o GD20, não todos os Takamine; e se o GF-3D
            # está esgotado, não devolvemos o GF-1R como se fosse ele.
            df = df[score == score.max()]
        if not incluir_indisponiveis:
            df = df[df["disponivel"]]
        # O filtro de preço usa o preço efetivo (promocional, se houver),
        # que é o que o cliente de fato paga no cartão.
        efetivo = df["price_brl"] * (1 - df["desconto_pct"].fillna(0) / 100)
        faixa = efetivo.between(
            preco_min if preco_min is not None else 0,
            preco_max if preco_max is not None else float("inf"),
        )
        df = df[faixa]
        df = df.sort_values("price_brl")
        return [self.ficha_produto(row) for _, row in df.head(limite).iterrows()]

    def produto(self, product_id: int) -> dict | None:
        if product_id not in self.produtos.index:
            return None
        return self.ficha_produto(self.produtos.loc[product_id], detalhada=True)

    # ----------------------------------------------------------------- pedidos

    def identificar_cliente(self, email_ou_telefone: str) -> pd.Series | None:
        chave = email_ou_telefone.strip().lower()
        if "@" in chave:
            achados = self.clientes[self.clientes["email_norm"] == chave]
        else:
            digitos = so_digitos(chave)
            if len(digitos) < 8:
                return None
            # Aceita com ou sem DDD/código do país: compara pelo final do número.
            achados = self.clientes[
                self.clientes["fone_norm"].apply(lambda f: f.endswith(digitos[-9:]) or digitos.endswith(f))
            ]
        return None if achados.empty else achados.iloc[0]

    def itens_do_pedido(self, order_id: int) -> list[dict]:
        itens = self.itens_pedido[self.itens_pedido["order_id"] == order_id]
        saida = []
        for _, item in itens.iterrows():
            pid = int(item["product_id"])
            nome = self.produtos.loc[pid, "name"] if pid in self.produtos.index else f"produto {pid}"
            saida.append({"produto_id": pid, "produto": nome, "quantidade": int(item["quantity"])})
        return saida

    def resumo_pedido(self, order_id: int) -> dict:
        p = self.pedidos.loc[order_id]
        return {
            "pedido": int(p["order_id"]),
            "data_compra": p["order_date"].isoformat(),
            "status": STATUS_PEDIDO.get(p["status"], p["status"]),
            "status_codigo": p["status"],
            "itens": self.itens_do_pedido(order_id),
            "total": float(p["total_brl"]),
            "pagamento": descrever_pagamento(p["payment_method"]),
            "codigo_rastreio": p["tracking_code"],
            "previsao_entrega": p["estimated_delivery"].isoformat() if p["estimated_delivery"] else None,
            "observacao": p["notes"],
        }

    def pedidos_do_cliente(self, customer_id: int) -> list[int]:
        return [int(i) for i in self.pedidos.index[self.pedidos["customer_id"] == customer_id]]
