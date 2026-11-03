# Preço, promoção expirada e produto esgotado com alternativas

> Gerado por `scripts/gerar_exemplos.py` com o modelo `gemini-3.6-flash`. Data/hora simulada: `2026-11-03T15:10`. As linhas `↳` mostram as ferramentas que o agente chamou.

**Cliente:** Quanto custa o Takamine GD20?

> ↳ `buscar_produtos({"termo": "Takamine GD20"}) -> {"resultados": [{"id": 95, "nome": "Takamine GD20 Dreadnought Natural", "categoria": "Violões", "preco_tabela": 2199.0, "status": "ativo", "estoque": 5, "disponivel": true, "preco_pix": 2089.05}]}`
> ↳ `simular_pagamento({"valor": 2199, "preco_promocional": false}) -> {"valor": 2199.0, "pix": 2089.05, "pix_obs": "5% de desconto", "debito_ou_boleto": 2199.0, "credito_max_parcelas_sem_juros": {"parcelas": 12, "valor_parcela": 183.25}, "pode_combinar_formas": true}`

**Lia:** O *Violão Takamine GD20 Dreadnought Natural* está custando R$ 2.199,00. 🎸

Confira as condições de pagamento:
- *À vista no PIX:* R$ 2.089,05 (com 5% de desconto)
- *Cartão de crédito:* até 12x de R$ 183,25 sem juros

Temos unidades em estoque! Se quiser saber mais detalhes ou tirar alguma dúvida sobre o instrumento, é só avisar.

---

**Cliente:** Vi que ele tava na Oferta Especial com 12% off, ainda vale?

> ↳ `consultar_politicas({"topico": "promocoes"}) -> {"topico": "promocoes", "texto": "Promoções e descontos\n\nCampanhas ao longo do ano:\n- Aniversário da Loja (agosto): 10% a 25% em itens selecionados.\n- Black Friday (novembro): 15% a 30% em todo o catálogo.\n- Volta à…`

**Lia:** Essa promoção de 12% off não está ativa no momento. 

Atualmente, o *Takamine GD20* está no preço normal de tabela por *R$ 2.199,00*, mas você garante 5% de desconto pagando no PIX (*R$ 2.089,05*) ou pode parcelar em até *12x de R$ 183,25 sem juros*.

Se precisar de mais alguma informação sobre o violão, estou à disposição!

---

**Cliente:** Entendi. E o Giannini GF-3D, tem aí?

> ↳ `buscar_produtos({"termo": "Giannini GF-3D"}) -> {"resultados": [], "encontrados_indisponiveis": [{"id": 96, "nome": "Giannini GF-3D Dreadnought Sunburst", "categoria": "Violões", "preco_tabela": 799.9, "status": "ativo", "estoque": 0, "disponivel": false, "preco_pix":…`
> ↳ `simular_pagamento({"preco_promocional": false, "valor": 579.9}) -> {"valor": 579.9, "pix": 550.9, "pix_obs": "5% de desconto", "debito_ou_boleto": 579.9, "credito_max_parcelas_sem_juros": {"parcelas": 6, "valor_parcela": 96.65}, "pode_combinar_formas": false}`

**Lia:** O *Giannini GF-3D Dreadnought Sunburst* está temporariamente indisponível no nosso estoque. 

Mas temos ótimas opções no mesmo estilo de violão folk em aço para te indicar:

- *Giannini GF-1R Aço Folk Sunburst:* R$ 579,90 (ou *R$ 550,90 no PIX* com 5% de desconto, ou em até 6x de R$ 96,65 sem juros) 🎸
- *Shelby SN-100 Folk Aço Preto:* R$ 549,00 (ou *R$ 521,55 no PIX*)

Alguma dessas alternativas atende ao que você procura?

---
