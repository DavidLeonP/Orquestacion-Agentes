# Resultados de ejecución del pipeline (API)

**Fecha (UTC):** 2026-07-12T20:39:45Z  
**Base URL:** `http://146.190.151.125:8000`  
**Estado:** completado con éxito  
**Duración total aproximada:** ~70 s  
**Script:** [`scripts/run_pipeline_api.py`](../scripts/run_pipeline_api.py)  
**JSON crudo:** [`_pipeline_run_raw.json`](_pipeline_run_raw.json)

## Resumen ejecutivo

| Paso | Endpoint | HTTP | Tiempo | Resultado |
|---|---|---|---|---|
| Health | `GET /api/v1/health` | 200 | 0.62 s | `openai_configured: true` |
| Ingesta | `POST /api/v1/ingestar` | 200 | 8.39 s | 12 chunks en 4 índices |
| Chat alumno (Tutor) | `POST /api/v1/chat` | 200 | 16.02 s | `completed` |
| Chat docente (examen) | `POST /api/v1/chat` | 200 | 28.16 s | `awaiting_approval` + veredicto APROBADO |
| Aprobación docente | `POST /api/v1/approve` | 200 | 0.82 s | `completed` (examen publicado) |
| Chat docente (currículo) | `POST /api/v1/chat` | 200 | 15.99 s | `completed` (12 sesiones) |

**Veredicto global:** el pipeline end-to-end vía API funciona: RAG indexa, el Tutor responde con ejemplos del material del instituto, el Exam Generator + Rubric validan, el human-in-the-loop aprueba, y el Curriculum Agent estructura la unidad alineada al currículo.

## 1. Health

```json
{
  "status": "ok",
  "service": "asistente-ia-educacion",
  "openai_configured": true
}
```

Contenedor reiniciado con `.env` sincronizado (`OPENAI_API_KEY` presente en el proceso).

## 2. Ingesta RAG

```json
{
  "status": "ok",
  "indices": {
    "apuntes": 4,
    "examenes": 4,
    "rubricas": 2,
    "curriculo": 2
  }
}
```

| Índice | Chunks | Origen típico |
|---|---|---|
| `apuntes` | 4 | Electricidad + circuitos (3º ESO) |
| `examenes` | 4 | Convocatorias 2023 y 2024 |
| `rubricas` | 2 | Criterios de diseño/corrección |
| `curriculo` | 2 | Programación didáctica bloque electricidad |

## 3. Tutor Agent (alumno)

- **thread_id:** `9d4e5f3d-eb43-44ff-9812-ce96ba633101`
- **Petición:** diferencia entre circuito en serie y en paralelo, con ejemplos del instituto.
- **Status:** `completed`

### Observaciones

- Usa los valores de los apuntes del centro (p. ej. bombillas 3 Ω / 6 Ω con pila de 9 V en serie; dos de 6 Ω con 12 V en paralelo).
- Incluye ejercicio resuelto + ejercicio propuesto al alumno (método socrático del Tutor).
- No entrega soluciones de examen activo.

### Extracto

> En un circuito en serie… `Req = R1 + R2 + R3`… ejemplo 3 Ω y 6 Ω a 9 V → `I = 1 A`.  
> En paralelo… `1/Req = 1/R1 + 1/R2`… dos bombillas de 6 Ω a 12 V → `Req = 3 Ω`, `Itotal = 4 A`.

## 4. Exam Generator + Rubric (docente)

- **thread_id:** `13aeba30-8177-476d-b371-3c61cf1de6cb`
- **Status intermedio:** `awaiting_approval`
- **Veredicto Rubric Agent:** `VEREDICTO: APROBADO`

### Cumplimiento de rúbrica (según el agente)

| Criterio | Resultado |
|---|---|
| Suma 10 puntos | Cumple |
| ≥ 3 tipos de pregunta (teoría, numérico, esquema) | Cumple |
| ≥ 40 % problemas numéricos | Cumple (4/10) |
| Pregunta de seguridad eléctrica | Cumple (P6) |
| Duración 55 min | Cumple |
| Valores numéricos sencillos 3º ESO | Cumple |

### Fuentes citadas por el Exam Generator

- `tecnologia_3eso_2023_electricidad.txt`
- `tecnologia_3eso_2024_electricidad.txt`
- `tecnologia_3eso_rubrica_examenes.txt`

### Estructura del examen generado

1. Definición de corriente eléctrica (1,5)  
2. Tabla magnitud / unidad / aparato (1,5)  
3. Motor 10 Ω / 20 V — intensidad y potencia (2)  
4. Esquema serie + fallo de bombilla (2)  
5. Paralelo 4 Ω y 8 Ω a 12 V (2)  
6. Elementos de protección / diferencial (1)  

Incluye solucionario.

## 5. Aprobación humana (`/api/v1/approve`)

```json
{ "thread_id": "13aeba30-8177-476d-b371-3c61cf1de6cb", "decision": "si" }
```

- **Status:** `completed`
- **Efecto:** se entrega el examen definitivo; el orquestador registra feedback/histórico en memoria de largo plazo.

## 6. Curriculum Agent (docente)

- **thread_id:** `95fdbe4f-0e45-4790-aa61-3fd98d6e6a6b`
- **Status:** `completed`
- **Salida:** unidad de **12 sesiones** (2º trimestre), alineada a códigos C1–C6 del currículo.

### Fuentes citadas

- `tecnologia_3eso_curriculo.txt`
- `tecnologia_3eso_electricidad.txt`
- `tecnologia_3eso_circuitos.txt`

### Mapa de sesiones (resumen)

| Sesiones | Tema |
|---|---|
| 1–3 | Corriente, magnitudes, medición |
| 4–6 | Ley de Ohm + evaluación parcial |
| 7–9 | Serie, paralelo, mixtos |
| 10–11 | Potencia/energía y seguridad |
| 12 | Examen de unidad |

## 7. Validación de directrices

| Directriz ([arquitectura.md](arquitectura.md)) | Evidencia en esta corrida |
|---|---|
| RAG multi-índice | Ingesta 4 índices; citas por tipo de fuente |
| Grounding / no responder “en general” | Ejemplos y valores del material del instituto |
| Validación cruzada Exam → Rubric | Veredicto APROBADO antes de human-in-the-loop |
| Human-in-the-loop | `awaiting_approval` → `approve` |
| Tutor con salvaguardas | Explica + propone ejercicio; no resuelve examen activo |
| Curriculum alineado al histórico | 12 sesiones con códigos C1–C6 del currículo |

## 8. Cómo reproducir

```bash
# Con el contenedor arriba y OPENAI_API_KEY configurada
python scripts/run_pipeline_api.py
# o contra local:
BASE_URL=http://localhost:8000 python scripts/run_pipeline_api.py
```

Orden de llamadas: health → ingestar → chat alumno → chat examen → approve → chat currículo.
