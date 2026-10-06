"""La aritmética de los cómputos la hace el sistema, no el modelo.

Corre con:  .venv\\Scripts\\python.exe -m tests.aritmetica_computo
"""
from __future__ import annotations

from backend.core.computo import evaluar_expresion, recalcular


def main() -> None:
    assert evaluar_expresion("45.00*2.80") == 126.0
    assert round(evaluar_expresion("-6*(0.90*2.10)"), 4) == -11.34
    assert evaluar_expresion("45,00 x 2,80") == 126.0
    assert evaluar_expresion("4 × 1,5") == 6.0
    for mala in ("__import__('os')", "2**10", "abs(-1)", "1/0", ""):
        try:
            evaluar_expresion(mala)
        except ValueError:
            continue
        raise AssertionError(f"debió rechazar {mala!r}")

    # Lo que hizo gpt-5.6-luna en §11.1: subtotal y cantidad mal sumados.
    partidas = [{"codigo_interno": "ALB-001", "unidad": "m2", "cantidad": 105.30, "mediciones": [
        {"expresion": "45.00*2.80", "subtotal": 126.0},
        {"expresion": "-6*(0.90*2.10)", "subtotal": -20.70},
    ]}]
    correcciones = recalcular(partidas)
    assert partidas[0]["cantidad"] == 114.66, partidas[0]["cantidad"]
    assert partidas[0]["mediciones"][1]["subtotal"] == -11.34
    assert len(correcciones) == 2, correcciones

    # Sin mediciones, la cantidad es dato del usuario y no se toca.
    sola = [{"codigo_interno": "X", "unidad": "m3", "cantidad": 480}]
    assert recalcular(sola) == [] and sola[0]["cantidad"] == 480
    print("[OK] aritmética de cómputos")


if __name__ == "__main__":
    main()
