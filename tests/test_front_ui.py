"""Front Streamlit: progreso y pasos con el ciclo de Reflexion (sin API ni navegador)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app_streamlit"))

from lib.labels import phase_progress  # noqa: E402
from lib.ui import _latest_node, _step_timeline  # noqa: E402

NODOS_REFLEXION = ["router", "exam_generator", "validar", "reflexionar", "exam_generator", "validar"]


def _eventos(nodos, final="waiting_approval"):
    return [{"tipo": "nodo_grafo", "payload": {"nodo": n}} for n in nodos] + [{"tipo": final}]


def test_timeline_muestra_cada_intento():
    pasos = _step_timeline(_eventos(NODOS_REFLEXION))
    assert pasos == [
        "✓ Clasificando la petición",
        "✓ Generando el examen",
        "✓ Validando con la rúbrica",
        "✓ Aprendiendo del rechazo",
        "✓ Generando el examen · intento 2",
        "✓ Validando con la rúbrica · intento 2",
        "✓ Listo para tu revisión",
    ]


def test_ultimo_nodo_y_fase_de_reflexion():
    assert _latest_node(_eventos(NODOS_REFLEXION)) == "aprobacion_docente"
    # Sin la cota de poll_request el progreso bajaría al volver a exam_generator
    assert phase_progress("exam_generator", "running") < phase_progress("reflexionar", "running")
