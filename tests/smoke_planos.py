"""Prueba del lector de planos sin base de datos ni modelo.

Arma un PDF mínimo con texto (como uno exportado desde CAD) y verifica qué
extrae `_parsear_pdf`: title block, cotas, diámetros, áreas y notas.

Corre con:  .venv\\Scripts\\python.exe -m tests.smoke_planos
"""
from __future__ import annotations

from backend.mcp.sotica_planos import _parsear_pdf
from scripts.plano_demo import pdf_una_pagina, plano, texto

LINEAS = [
    "PROYECTO: Casa Los Robles",
    "LAMINA: A-01",
    "ESCALA: 1:50",
    "Muro eje 4: 4,50 m",
    "Tuberia PVC \xd8 110 mm y \xd8 4\" aguas negras",
    "Losa: 12,50 m\xb2",
    "Concreto: 3,20 m3",
    "NOTA: cotas en metros",
]


def _pdf(lineas: list[str]) -> bytes:
    return pdf_una_pagina("".join(texto(50, 750 - 14 * i, t) for i, t in enumerate(lineas)), 612, 792)


def main() -> None:
    r = _parsear_pdf(_pdf(LINEAS), max_paginas=50)
    print(r)
    assert r["paginas_totales"] == 1
    assert r["title_block"]["PROYECTO"] == "Casa Los Robles"
    assert r["title_block"]["LAMINA"] == "A-01"
    assert r["dimensiones_lineales_detectadas"] == ["4,50 m"]
    assert r["diametros_detectados"] == ['Ø 110 mm', 'Ø 4"']
    assert r["areas_detectadas"] == ["12,50 m²"]
    assert r["volumenes_detectados"] == ["3,20 m3"]
    assert r["notas_del_plano"] == ["cotas en metros"]
    assert r["advertencia_datos"] == []

    vacio = _parsear_pdf(_pdf(["Plano sin cotas"]), max_paginas=50)
    assert vacio["advertencia_datos"], "debe advertir cuando no hay medidas"
    assert "Casa Los Robles" in r["paginas"][0]["texto"]

    demo = _parsear_pdf(plano(), max_paginas=50)
    assert demo["title_block"]["LAMINA"] == "A-02"
    assert "Muro interior eje 2: 8,00 m" in demo["paginas"][0]["texto"]
    assert "P-1 puerta 0,90 x 2,10 m - cantidad 4" in demo["paginas"][0]["texto"]
    print("[OK] lector de planos")


if __name__ == "__main__":
    main()
