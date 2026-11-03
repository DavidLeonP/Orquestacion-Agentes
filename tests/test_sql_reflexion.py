"""Validación/reflexión del SQL Agent (sin red)."""

from __future__ import annotations

from src.sql_agent.reflexion import (
    bloque_memoria,
    siguiente_paso_sql,
    verificar_respuesta,
)
from src.sql_agent.schemas import VeredictoSql


def test_rechaza_anio_ingreso_para_matricula_anio_pasado():
    v = verificar_respuesta(
        "¿Cuáles son los estudiantes que se matricularon el año pasado?",
        "Hay 83 estudiantes…",
        "SELECT e.codigo FROM estudiantes e "
        "JOIN matriculas m ON m.estudiante_id = e.id WHERE e.anio_ingreso = 2022",
    )
    assert not v.aprobado
    assert v.necesita_aclaracion
    assert v.pregunta_aclaracion
    assert any("anio_ingreso" in m for m in v.motivos)


def test_aprueba_filtro_por_periodo():
    v = verificar_respuesta(
        "¿Cuáles son los estudiantes que se matricularon el año pasado?",
        "Hay 500 estudiantes en 2024-2025…",
        "SELECT DISTINCT e.codigo FROM matriculas m "
        "JOIN ofertas o ON o.id = m.oferta_id "
        "JOIN periodos p ON p.id = o.periodo_id "
        "JOIN estudiantes e ON e.id = m.estudiante_id "
        "WHERE p.anio_fin = (SELECT MAX(anio_fin) FROM periodos)",
    )
    assert v.aprobado
    assert not v.necesita_aclaracion


def test_cohorte_ingreso_permite_anio_ingreso():
    v = verificar_respuesta(
        "¿Cuántos estudiantes ingresaron en 2022 (cohorte de ingreso)?",
        "83",
        "SELECT COUNT(*) FROM estudiantes WHERE anio_ingreso = 2022",
    )
    assert v.aprobado


def test_siguiente_paso_duda_pide_humano():
    v = VeredictoSql(
        aprobado=False,
        necesita_aclaracion=True,
        motivos=["ambigüedad"],
        pregunta_aclaracion="¿Periodo o cohorte?",
    )
    assert siguiente_paso_sql(v, intentos=1) == "aclaracion_humana"


def test_siguiente_paso_rechazo_sin_duda_reflexiona():
    v = VeredictoSql(aprobado=False, motivos=["respuesta vacía"])
    assert siguiente_paso_sql(v, intentos=1) == "reflexionar"


def test_bloque_memoria_incluye_aclaraciones():
    txt = bloque_memoria(
        ["Petición parecida: año pasado\nAclaración: usa periodos"],
        ["Intento SQL 1: mal filtro Plan: usar periodos"],
    )
    assert "ACLARACIONES APRENDIDAS" in txt
    assert "LECCIONES DE ESTA PETICIÓN" in txt
