"""CLI del Asistente IA para Educación.

Uso:
  python main.py ingestar                    Construye los índices RAG
  python main.py docente "petición"          Petición como docente
  python main.py alumno "petición" [id]      Petición como alumno
  python main.py demo                        Ejecuta los escenarios de ejemplo
  python main.py trazas [N]                  Resumen de las últimas N trazas
"""

import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

# Consola Windows: evita errores al imprimir caracteres Unicode (Ω, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.observability.trazas import (  # noqa: E402
    TrazasSolicitud,
    configurar_observabilidad,
    config_langgraph,
    registrar_evento,
    resumir_trazas,
)


def _invocar_grafo(app, entrada: dict, config: dict) -> dict:
    """Ejecuta el grafo registrando cada nodo completado."""
    estado: dict = {}
    for chunk in app.stream(entrada, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            estado["__interrupt__"] = chunk["__interrupt__"]
            registrar_evento("grafo_interrupcion", motivo="human_in_the_loop")
        for nodo, actualizacion in chunk.items():
            if nodo.startswith("__"):
                continue
            if not isinstance(actualizacion, dict):
                continue
            estado.update(actualizacion)
            registrar_evento(
                "nodo_grafo",
                nodo=nodo,
                claves=list(actualizacion.keys()),
            )
    return estado


def _ejecutar(peticion: str, rol: str, alumno_id: str = "anonimo") -> None:
    from langgraph.types import Command

    from src.orchestrator.graph import construir_grafo

    configurar_observabilidad()
    app = construir_grafo()
    run_id = str(uuid.uuid4())
    config = config_langgraph(run_id, rol, peticion, alumno_id)

    print(f"\n[{rol}] {peticion}\n{'=' * 70}")

    with TrazasSolicitud(run_id, rol, peticion, alumno_id):
        estado = _invocar_grafo(
            app,
            {"peticion": peticion, "rol_usuario": rol, "alumno_id": alumno_id},
            config,
        )

        while "__interrupt__" in estado:
            datos = estado["__interrupt__"][0].value
            print("\n--- BORRADOR PENDIENTE DE APROBACIÓN ---\n")
            print(datos.get("borrador", ""))
            print("\n--- VALIDACIÓN CRUZADA (Rubric Agent) ---\n")
            veredicto = datos.get("veredicto", "")
            if isinstance(veredicto, dict):
                from src.agents.schemas import (
                    VeredictoValidacion,
                    render_veredicto,
                    safe_parse,
                )

                v, _ = safe_parse(VeredictoValidacion, veredicto)
                veredicto = render_veredicto(v)
            print(veredicto)
            decision = input(f"\n{datos.get('mensaje', '¿Apruebas?')} > ").strip() or "si"
            estado = _invocar_grafo(app, Command(resume=decision), config)

        registrar_evento(
            "respuesta_entregada",
            longitud=len(estado.get("respuesta_final", "")),
            tiene_fuentes="fuentes consultadas"
            in estado.get("respuesta_final", "").lower(),
        )

    print("\n--- RESPUESTA FINAL ---\n")
    print(estado["respuesta_final"])
    print(f"\n[Trazas] storage/logs/{run_id}.jsonl")


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
    elif comando == "trazas":
        configurar_observabilidad()
        ultimas = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(resumir_trazas(ultimas))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
