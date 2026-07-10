"""Crea todas las tablas en MySQL remoto."""

from src.db.models import (  # noqa: F401
    Approval,
    Chunk,
    ChunkEmbedding,
    Document,
    MemoryFeedback,
    MemoryHistorico,
    MemoryPerfilAlumno,
    Request,
    RequestEvent,
    User,
)
from src.db.session import Base, engine


def main() -> None:
    print(f"Creando tablas en {engine.url.render_as_string(hide_password=True)} ...")
    Base.metadata.create_all(bind=engine)
    print("Tablas creadas / verificadas correctamente.")


if __name__ == "__main__":
    main()
