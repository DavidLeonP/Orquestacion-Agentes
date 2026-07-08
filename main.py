"""CLI del Asistente IA para Educación.

Uso:
  python main.py ingestar                    Construye los índices RAG
  python main.py docente "petición"          Petición como docente
  python main.py alumno "petición" [id]      Petición como alumno
  python main.py demo                        Ejecuta los escenarios de ejemplo
"""

import sys
import uuid

from dotenv import load_dotenv

load_dotenv()


def _ejecutar(peticion: str, rol: str, alumno_id: str = "anonimo") -> None:
    from langgraph.types import Command

    from src.orchestrator.graph import construir_grafo

    app = construir_grafo()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print(f"\n[{rol}] {peticion}\n{'=' * 70}")
    estado = app.invoke(
        {"peticion": peticion, "rol_usuario": rol, "alumno_id": alumno_id},
        config=config,
    )

    # Human-in-the-loop: el grafo se interrumpe esperando la aprobación docente.
    while "__interrupt__" in estado:
        datos = estado["__interrupt__"][0].value
        print("\n--- BORRADOR PENDIENTE DE APROBACIÓN ---\n")
        print(datos["borrador"])
        print("\n--- VALIDACIÓN CRUZADA (Rubric Agent) ---\n")
        print(datos["veredicto"])
        decision = input(f"\n{datos['mensaje']} > ").strip() or "si"
        estado = app.invoke(Command(resume=decision), config=config)

    print("\n--- RESPUESTA FINAL ---\n")
    print(estado["respuesta_final"])


def demo() -> None:
    escenarios = [
        ("docente", "Estructura la unidad de electricidad de Tecnología de 3º ESO "
                    "en sesiones, alineada con la programación del centro."),
        ("docente", "Genera un examen de 6 preguntas sobre electricidad y circuitos "
                    "para Tecnología de 3º ESO, dificultad media, 55 minutos."),
        ("alumno", "No entiendo la diferencia entre circuito en serie y en "
                   "paralelo, ¿me lo explicas?"),
    ]
    for rol, peticion in escenarios:
        _ejecutar(peticion, rol)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    comando = sys.argv[1]
    if comando == "ingestar":
        from src.ingestion.pipeline import ingestar

        ingestar()
    elif comando == "docente" and len(sys.argv) >= 3:
        _ejecutar(sys.argv[2], "docente")
    elif comando == "alumno" and len(sys.argv) >= 3:
        alumno_id = sys.argv[3] if len(sys.argv) > 3 else "anonimo"
        _ejecutar(sys.argv[2], "alumno", alumno_id)
    elif comando == "demo":
        demo()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
