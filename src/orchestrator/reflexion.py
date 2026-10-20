"""Reflexion sobre la generación de exámenes (docs/arquitectura.md §5.4).

Funciones puras, sin LLM: el grafo las usa para decidir y aquí se prueban
sin red. Roles de Reflexion (Shinn et al., 2023):

- Actor: Exam Generator. Regenera con la trayectoria limpia y las lecciones o, si
  el examen solo falla en criterios puntuales, repara el borrador (`modo_reintento`).
- Evaluador: `verificar_examen` (gratis: constraints, fuentes y criterios de la
  rúbrica) y, si pasa, el Rubric Agent (LLM).
- Auto-reflexión: nodo `reflexionar` del grafo, que escribe una lección.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.agents.schemas import ConstraintsExamen, CriteriosRubrica, ExamenGenerado, Reflexion

MAX_INTENTOS = 2

SIN_PREGUNTAS = "El examen no tiene preguntas estructuradas."
SIN_CITAS = "No cita las fuentes consultadas."
SIN_CONSULTAS = "No consultó ninguna fuente con las herramientas."
CITAS_INVENTADAS = "Cita fuentes que no consultó con las herramientas"
# Errores que exigen volver a investigar: reparar el borrador no los arregla
PREFIJOS_REGENERAR = (SIN_PREGUNTAS, SIN_CITAS, SIN_CONSULTAS, CITAS_INVENTADAS)


def _verificar_criterios(examen: ExamenGenerado, criterios: CriteriosRubrica) -> list[str]:
    preguntas = examen.preguntas
    errores = []
    if criterios.requiere_seguridad and not any(p.tipo == "seguridad" for p in preguntas):
        errores.append("La rúbrica exige una pregunta de seguridad y no hay ninguna.")
    total = sum(p.puntuacion for p in preguntas)
    numerico = (
        sum(p.puntuacion for p in preguntas if p.tipo == "numerico" or p.con_calculo) / total
        if total else 0
    )
    if numerico + 1e-9 < criterios.pct_min_numerico:
        errores.append(
            f"Los problemas numéricos suman el {numerico:.0%} de la puntuación y la rúbrica "
            f"exige al menos el {criterios.pct_min_numerico:.0%}."
        )
    tipos = {p.tipo for p in preguntas} - {"otro"}
    # Con pocas preguntas no caben más tipos que preguntas
    minimo = min(criterios.tipos_minimos, len(preguntas))
    if len(tipos) < minimo:
        errores.append(f"Hay {len(tipos)} tipos de pregunta y la rúbrica exige al menos {minimo}.")
    return errores


def verificar_examen(
    examen: ExamenGenerado,
    constraints: ConstraintsExamen,
    vistas: list[str] | None = None,
    criterios: CriteriosRubrica | None = None,
) -> list[str]:
    """Incumplimientos comprobables sin LLM; lista vacía si no hay.

    `vistas`: fuentes que devolvieron las tools RAG (None = no se registraron).
    `criterios`: criterios objetivos de la rúbrica del docente (None = no se comprueban).
    """
    preguntas = examen.preguntas
    if not preguntas:
        return [SIN_PREGUNTAS]
    errores = []
    if len(preguntas) != constraints.num_preguntas:
        errores.append(
            f"Tiene {len(preguntas)} preguntas y se pidieron {constraints.num_preguntas}."
        )
    total = sum(p.puntuacion for p in preguntas)
    if abs(total - constraints.puntuacion_total) > 0.01:
        errores.append(
            f"Las puntuaciones suman {total:g} y el total debe ser {constraints.puntuacion_total:g}."
        )
    if [p.numero for p in preguntas] != list(range(1, len(preguntas) + 1)):
        errores.append("Las preguntas no están numeradas de 1 a N.")
    sin_solucion = [p.numero for p in preguntas if not p.solucion.strip()]
    if sin_solucion and not examen.solucionario.strip():
        errores.append(f"Faltan soluciones en las preguntas {sin_solucion}.")
    citadas = [f for f in examen.fuentes if f.strip()]
    if not citadas:
        errores.append(SIN_CITAS)
    elif vistas is not None:
        if not vistas:
            errores.append(SIN_CONSULTAS)
        else:
            # Una cita vale si nombra (palabra completa) un archivo devuelto por las tools,
            # con o sin extensión: "apuntes" no valida "apuntes_inventados.pdf"
            stems = [re.compile(rf"(?<!\w){re.escape(Path(v).stem.lower())}(?!\w)") for v in vistas]
            inventadas = [f for f in citadas if not any(s.search(f.lower()) for s in stems)]
            if inventadas:
                errores.append(f"{CITAS_INVENTADAS}: {inventadas}.")
    if criterios is not None:
        errores += _verificar_criterios(examen, criterios)
    return errores


def modo_reintento(intento: dict) -> str:
    """'reparar' si el borrador es aprovechable (solo falla criterios puntuales o la
    rúbrica LLM); 'regenerar' si no tiene preguntas o sus fuentes no valen."""
    if not intento["examen"].get("preguntas") or any(
        e.startswith(PREFIJOS_REGENERAR) for e in intento["errores"]
    ):
        return "regenerar"
    return "reparar"


def _bloque(titulo: str, lineas: list[str]) -> str:
    return f"\n\n{titulo}\n" + "\n".join(f"- {l}" for l in lineas) if lineas else ""


def peticion_examen(
    peticion: str,
    constraints: ConstraintsExamen,
    lecciones: list[str],
    reglas: list[str] = (),
    casos: list[str] = (),
    reparar: dict | None = None,
) -> str:
    """Prompt del Actor: petición + constraints + memoria.

    reglas: manual aprendido en entrenamiento; casos: exámenes aprobados parecidos;
    lecciones: Reflexion de los intentos rechazados de esta petición.
    reparar: el intento rechazado. Si se pasa, se pide corregir ese borrador en vez de
    generar uno nuevo (Reflexion pura nunca ve el borrador; la reparación sí, a propósito).
    """
    texto = (
        f"{peticion}\n\nConstraints tipadas (respétalas):\n"
        f"{constraints.model_dump_json(indent=2)}"
        + _bloque("Reglas aprendidas (cúmplelas):", list(reglas))
        + _bloque("Exámenes aprobados parecidos (pistas de estilo; no los copies):", list(casos))
        + _bloque("Intentos anteriores fueron rechazados. Aplica estas lecciones:", lecciones)
    )
    if reparar:
        v = reparar["veredicto"]
        texto += (
            _bloque("CORRIGE este borrador. Motivos del rechazo:", v["motivos"] or [v["resumen"]])
            + "\nConserva las preguntas que ya cumplen y cambia o añade solo lo necesario "
            "(usa las herramientas si te falta material). Entrega el examen COMPLETO "
            "corregido, con solucionario y fuentes consultadas.\n\nBORRADOR:\n"
            + reparar["borrador"]
        )
    return texto


def prompt_reflexion(peticion: str, borrador: str, motivos: list[str], previas: list[str]) -> str:
    """Prompt del Reflector; lo comparten el grafo y scripts/entrenar_reglas.py."""
    return (
        "Ayudas al Exam Generator a aprender de un intento rechazado.\n\n"
        f"PETICIÓN:\n{peticion}\n\n"
        f"BORRADOR RECHAZADO:\n{borrador}\n\n"
        "MOTIVOS DEL RECHAZO:\n" + "\n".join(f"- {m}" for m in motivos) + "\n\n"
        "LECCIONES PREVIAS:\n" + ("\n".join(previas) or "(ninguna)") + "\n\n"
        "Diagnostica qué paso causó el rechazo (búsqueda insuficiente, constraint "
        "ignorada, rúbrica no consultada...) y propón un plan concreto: qué buscar "
        "con buscar_examenes_historicos, buscar_apuntes o buscar_rubricas y qué "
        "cambiar. No repitas lecciones previas. En regla_general escribe una regla "
        "que sirva para OTROS exámenes, sin datos de esta petición."
    )


def leccion(numero: int, reflexion: Reflexion) -> str:
    return f"Intento {numero}: {reflexion.diagnostico} Plan: {reflexion.plan}"


def siguiente_paso(intentos: list[dict]) -> str:
    """Tras validar: al docente si aprobó o se agotaron intentos; si no, reflexionar."""
    if intentos[-1]["veredicto"]["aprobado"] or len(intentos) >= MAX_INTENTOS:
        return "aprobacion_docente"
    return "reflexionar"


def mejor_intento(intentos: list[dict]) -> dict:
    """El aprobado; si ninguno, el primero con menos errores deterministas.

    Evita entregar el último intento cuando reflexionar lo empeoró.
    """
    return min(intentos, key=lambda i: (not i["veredicto"]["aprobado"], len(i["errores"])))
