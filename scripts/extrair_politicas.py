"""Extrai o texto bruto do PDF de políticas para data/processed/politicas_raw.txt.

O PDF sai com uma palavra por linha e as tabelas perdem a estrutura, então o
texto bruto serve só como base: a versão usada pelo agente é
data/politicas.md, revisada à mão a partir desta extração (ver README).

Uso: python scripts/extrair_politicas.py
"""

import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "raw" / "politicas_da_loja.pdf"
OUT = ROOT / "data" / "processed" / "politicas_raw.txt"


def main() -> None:
    reader = PdfReader(PDF)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = re.sub(r"\s+", " ", page.extract_text()).strip()
        pages.append(f"--- página {i} ---\n{text}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n\n".join(pages), encoding="utf-8")
    print(f"{len(reader.pages)} páginas extraídas para {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
