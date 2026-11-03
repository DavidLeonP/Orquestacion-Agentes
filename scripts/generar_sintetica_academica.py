#!/usr/bin/env python3
"""Genera el JSON canónico de la BD sintética académica (500 estudiantes).

Uso:
  python scripts/generar_sintetica_academica.py
  python scripts/generar_sintetica_academica.py --seed 42 --n-estudiantes 500
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sintetica_academica"
OUT_JSON = OUT_DIR / "estudiantes_sinteticos.json"

FACULTADES = [
    {"id": 1, "codigo": "FCI", "nombre": "Facultad de Ciencias e Ingeniería"},
    {"id": 2, "codigo": "FAE", "nombre": "Facultad de Administración y Economía"},
    {"id": 3, "codigo": "FCCSS", "nombre": "Facultad de Ciencias Sociales"},
]

CARRERAS = [
    {"id": 1, "facultad_id": 1, "codigo": "SIS", "nombre": "Ingeniería en Sistemas"},
    {"id": 2, "facultad_id": 1, "codigo": "IND", "nombre": "Ingeniería Industrial"},
    {"id": 3, "facultad_id": 2, "codigo": "ADM", "nombre": "Administración de Empresas"},
    {"id": 4, "facultad_id": 2, "codigo": "FIN", "nombre": "Finanzas"},
    {"id": 5, "facultad_id": 3, "codigo": "PSI", "nombre": "Psicología"},
]

MATERIAS = [
    {"id": 1, "codigo": "MAT101", "nombre": "Cálculo I", "creditos": 4, "carrera_id": None},
    {"id": 2, "codigo": "MAT102", "nombre": "Cálculo II", "creditos": 4, "carrera_id": None},
    {"id": 3, "codigo": "FIS101", "nombre": "Física I", "creditos": 4, "carrera_id": 1},
    {"id": 4, "codigo": "PRG101", "nombre": "Programación I", "creditos": 3, "carrera_id": 1},
    {"id": 5, "codigo": "PRG201", "nombre": "Estructuras de Datos", "creditos": 3, "carrera_id": 1},
    {"id": 6, "codigo": "BD301", "nombre": "Bases de Datos", "creditos": 3, "carrera_id": 1},
    {"id": 7, "codigo": "EST201", "nombre": "Estadística", "creditos": 3, "carrera_id": None},
    {"id": 8, "codigo": "ECO101", "nombre": "Introducción a la Economía", "creditos": 3, "carrera_id": 2},
    {"id": 9, "codigo": "CON201", "nombre": "Contabilidad Financiera", "creditos": 3, "carrera_id": 3},
    {"id": 10, "codigo": "FIN301", "nombre": "Finanzas Corporativas", "creditos": 3, "carrera_id": 4},
    {"id": 11, "codigo": "MKT201", "nombre": "Mercadotecnia", "creditos": 3, "carrera_id": 3},
    {"id": 12, "codigo": "PSI101", "nombre": "Psicología General", "creditos": 3, "carrera_id": 5},
    {"id": 13, "codigo": "ING101", "nombre": "Inglés Académico", "creditos": 2, "carrera_id": None},
    {"id": 14, "codigo": "ETI101", "nombre": "Ética Profesional", "creditos": 2, "carrera_id": None},
    {"id": 15, "codigo": "OPR301", "nombre": "Investigación de Operaciones", "creditos": 3, "carrera_id": 2},
]

NOMBRES = [
    "Ana", "Luis", "María", "Carlos", "Elena", "Diego", "Paula", "Andrés", "Sofía", "José",
    "Camila", "Mateo", "Valentina", "Sebastián", "Isabella", "Nicolás", "Daniela", "Gabriel",
    "Fernanda", "Ricardo", "Alejandra", "Felipe", "Carolina", "Emilio", "Lucía", "Tomás",
    "Martina", "Joaquín", "Antonia", "Benjamín",
]
APELLIDOS = [
    "Pérez", "Gómez", "Ruiz", "Díaz", "Soto", "Vargas", "Castro", "Morales", "Herrera",
    "Ramos", "Jiménez", "Ortiz", "Silva", "Mendoza", "Guerrero", "Romero", "Navarro",
    "Flores", "Acosta", "Benítez", "Cordero", "Espinoza", "Quintero", "Salazar", "Torres",
]


def _periodos() -> list[dict]:
    out = []
    for i, anio in enumerate(range(2019, 2025), start=1):
        out.append(
            {
                "id": i,
                "codigo": f"{anio}-{anio + 1}",
                "anio_inicio": anio,
                "anio_fin": anio + 1,
            }
        )
    return out


def _paralelos() -> list[dict]:
    return [{"id": i, "codigo": c} for i, c in enumerate(("A", "B", "C"), start=1)]


def _profesores(rng: random.Random) -> list[dict]:
    out = []
    for i in range(1, 25):
        fac = FACULTADES[(i - 1) % len(FACULTADES)]["id"]
        nom = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
        out.append(
            {
                "id": i,
                "codigo": f"PROF-{i:03d}",
                "nombre": nom,
                "email": f"prof{i:03d}@uandina-demo.ec",
                "facultad_id": fac,
            }
        )
    return out


def _nota(rng: random.Random, sesgo: float = 0.0) -> float:
    # Normal truncada ~ media 7.0
    v = rng.gauss(7.0 + sesgo, 1.35)
    return round(min(10.0, max(3.5, v)), 2)


def generar(n_estudiantes: int, seed: int) -> dict:
    rng = random.Random(seed)
    periodos = _periodos()
    paralelos = _paralelos()
    profesores = _profesores(rng)

    # Ofertas: cada periodo × materia × paralelo con un profesor
    ofertas = []
    oid = 1
    for per in periodos:
        for mat in MATERIAS:
            for par in paralelos:
                prof = profesores[(oid + mat["id"] + par["id"]) % len(profesores)]
                ofertas.append(
                    {
                        "id": oid,
                        "periodo_id": per["id"],
                        "materia_id": mat["id"],
                        "profesor_id": prof["id"],
                        "paralelo_id": par["id"],
                    }
                )
                oid += 1

    ofertas_por_clave = {
        (o["periodo_id"], o["materia_id"], o["paralelo_id"]): o for o in ofertas
    }

    estudiantes = []
    matriculas = []
    calificaciones = []
    promedios = []
    mid = 1
    cid = 1
    pid = 1

    # Reparto ~uniforme en 6 cohortes (anio_ingreso)
    for i in range(1, n_estudiantes + 1):
        carrera = CARRERAS[(i - 1) % len(CARRERAS)]
        paralelo = paralelos[(i - 1) % 3]
        cohorte_idx = (i - 1) % 6  # 0..5 → 2019..2024
        anio_ingreso = 2019 + cohorte_idx
        nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}"
        est = {
            "id": i,
            "codigo": f"EST-{i:04d}",
            "nombre": nombre,
            "email": f"est{i:04d}@estudiantes.uandina-demo.ec",
            "carrera_id": carrera["id"],
            "paralelo_ingreso_id": paralelo["id"],
            "anio_ingreso": anio_ingreso,
        }
        estudiantes.append(est)

        sesgo = rng.uniform(-0.6, 0.8)
        # Periodos en los que cursa: desde ingreso hasta 2024-2025
        periodos_activos = [p for p in periodos if p["anio_inicio"] >= anio_ingreso]
        for per in periodos_activos:
            # 4–6 materias por periodo, preferentemente de su carrera + transversales
            candidatas = [
                m
                for m in MATERIAS
                if m["carrera_id"] in (None, carrera["id"])
            ]
            k = min(len(candidatas), rng.randint(4, 6))
            elegidas = rng.sample(candidatas, k=k)
            notas_periodo: list[tuple[int, float]] = []
            for mat in elegidas:
                oferta = ofertas_por_clave[(per["id"], mat["id"], paralelo["id"])]
                matriculas.append(
                    {
                        "id": mid,
                        "estudiante_id": i,
                        "oferta_id": oferta["id"],
                        "estado": "aprobada",
                    }
                )
                nota = _nota(rng, sesgo)
                calificaciones.append(
                    {
                        "id": cid,
                        "matricula_id": mid,
                        "nota": nota,
                        "convocatoria": "ordinaria",
                    }
                )
                notas_periodo.append((mat["id"], nota))
                mid += 1
                cid += 1
            if notas_periodo:
                promedio = round(sum(n for _, n in notas_periodo) / len(notas_periodo), 3)
                afinidad = max(notas_periodo, key=lambda t: t[1])[0]
                promedios.append(
                    {
                        "id": pid,
                        "estudiante_id": i,
                        "periodo_id": per["id"],
                        "promedio": promedio,
                        "materia_afinidad_id": afinidad,
                        "num_materias": len(notas_periodo),
                    }
                )
                pid += 1

    return {
        "meta": {
            "universidad": "Universidad Andina Demo (Quito)",
            "generado_utc": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "n_estudiantes": n_estudiantes,
            "escala_notas": "0-10",
            "periodos": 6,
            "paralelos": ["A", "B", "C"],
        },
        "facultades": FACULTADES,
        "carreras": CARRERAS,
        "periodos": periodos,
        "paralelos": paralelos,
        "materias": MATERIAS,
        "profesores": profesores,
        "estudiantes": estudiantes,
        "ofertas": ofertas,
        "matriculas": matriculas,
        "calificaciones": calificaciones,
        "promedios_periodo": promedios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estudiantes", type=int, default=500)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    args = parser.parse_args()

    data = generar(args.n_estudiantes, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK {args.out} | estudiantes={len(data['estudiantes'])} "
        f"matriculas={len(data['matriculas'])} calificaciones={len(data['calificaciones'])} "
        f"promedios={len(data['promedios_periodo'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
