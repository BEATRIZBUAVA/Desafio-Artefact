"""Lista inconsistências encontradas nos CSVs (a base da seção de tratamento
de dados do README).

Uso: python scripts/relatorio_qualidade.py
"""

import sys

from emporio.data import Store, marcas_conflitantes


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    s = Store()
    p = s.produtos
    achados = []

    for _, r in p[(p["status"] == "active") & (p["stock_quantity"] <= 0)].iterrows():
        achados.append(f"Produto {r.product_id} ({r['name']}) ativo com estoque 0 -> tratado como esgotado")
    for _, r in p[(p["status"] != "active") & (p["stock_quantity"] > 0)].iterrows():
        achados.append(
            f"Produto {r.product_id} ({r['name']}) com status '{r.status}' e estoque {r.stock_quantity} -> não ofertado"
        )

    promo = s._csv("promotions")
    repetidas = promo[promo.duplicated("product_id", keep=False)].groupby("product_id").size()
    for pid, n in repetidas.items():
        achados.append(f"Produto {pid} tem {n} promoções cadastradas (só as ativas valem)")
    achados.append(f"{int((promo['is_active'] == 1).sum())} de {len(promo)} promoções estão ativas")

    for oid, pedido in s.pedidos.iterrows():
        itens = s.itens_pedido[s.itens_pedido["order_id"] == oid]
        soma = sum(p.loc[i.product_id, "price_brl"] * i.quantity for i in itens.itertuples())
        if abs(soma - pedido["total_brl"]) > 0.01:
            achados.append(
                f"Pedido {oid}: total R$ {pedido['total_brl']} difere da soma dos itens a preço atual "
                f"(R$ {soma:.2f}) -> exibimos o total registrado"
            )
        for i in itens.itertuples():
            st = p.loc[i.product_id, "status"]
            if st != "active" and pedido["status"] != "cancelled":
                achados.append(f"Pedido {oid} contém o produto {i.product_id}, hoje com status '{st}'")

    for _, r in p.iterrows():
        conflito = marcas_conflitantes(r["name"], r["description"])
        if conflito:
            achados.append(
                f"Produto {r.product_id}: nome cita {conflito[0]} mas a descrição cita {conflito[1]} -> descrição omitida"
            )

    print(f"{len(p)} produtos, {len(s.pedidos)} pedidos, {len(s.clientes)} clientes\n")
    for a in achados:
        print("-", a)


if __name__ == "__main__":
    main()
