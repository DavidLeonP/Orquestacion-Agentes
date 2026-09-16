#!/usr/bin/env python3
"""Estima coste de ingestión de un módulo (PDF + vídeo) sin embeddings ni ASR.

Ejemplos:
  python scripts/estimate_module_ingest.py contabilidadFinaciera
  python scripts/estimate_module_ingest.py contabilidadFinaciera --write-doc
  python scripts/estimate_module_ingest.py contabilidadFinaciera --json-out storage/metrics/cf.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.module_media import (  # noqa: E402
    guardar_informe_estimacion,
    estimar_coste_modulo,
    preparar_modulo,
    resolver_ruta_modulo,
)


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v < 0.01:
        return f"${v:.6f}"
    return f"${v:.4f}"


def _render_markdown(modulo: str, data: dict) -> str:
    inv = data["inventario"]["resumen"]
    oa = data["cloud_openai"]
    us = data["vllm_usfq"]
    fuentes = data["fuentes"]
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dur_min = inv["duration_sec_total"] / 60.0

    filas = []
    for f in fuentes:
        dur = f.get("duration_sec")
        dur_s = f"{dur/60:.1f} min" if dur else "—"
        filas.append(
            f"| `{f['filename']}` | {f['kind']} | {f['chars']:,} | "
            f"{f['tokens_approx']:,} | {f['chunks']} | {dur_s} |"
        )

    return f"""# Costo computacional de embeddings — módulo `{modulo}`

**Generado (UTC):** {ahora}  
**Modo:** estimación en seco (sin ASR, sin embeddings, sin escritura en MySQL)  
**Script:** `scripts/estimate_module_ingest.py`  
**Ruta inventariada:** `{data['inventario']['module_path']}`

## 1. Objetivo

Cuantificar el **costo computacional y económico** de preparar e indexar el módulo
de conocimiento del profesor (PDF + grabaciones de clase) para el RAG MySQL del
asistente, comparando:

1. **OpenAI como cerebro** (`LLM_PROFILE=cloud_openai`): Whisper API + `text-embedding-3-small`
2. **Infraestructura universidad** (`LLM_PROFILE=vllm_usfq`): ASR on-prem + `BAAI/bge-m3` vía vLLM

Esta estimación **no ejecuta** la carga: sirve para decidir presupuesto y métricas
antes de un ingest real.

## 2. Inventario del módulo

| Métrica | Valor |
|---|---|
| PDFs | {inv['pdfs']} |
| Vídeos | {inv['videos']} |
| Textos | {inv['textos']} |
| Peso total | {inv['bytes_totales'] / (1024**3):.2f} GB |
| Duración vídeo | **{dur_min:.1f} min** ({dur_min/60:.2f} h) |
| Chars PDF (capa de texto) | {inv['pdf_chars_total']:,} |

### Detalle por fuente

| Archivo | Tipo | Chars (est.) | Tokens (≈) | Chunks (≈) | Duración |
|---|---|---:|---:|---:|---|
{chr(10).join(filas)}

**Chunking alineado al pipeline:** `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)`  
(`src/ingestion/mysql_pipeline.py`).

**Transcripción de vídeo (dry-run):** densidad heurística
`CHARS_POR_MINUTO_ESTIMADOS = 720` (clase en español). El valor real saldrá del ASR.

## 3. Escenario A — OpenAI (cloud)

| Concepto | Modelo / tarifa | Resultado |
|---|---|---|
| ASR | `whisper-1` @ $0.006 / min | **{_fmt_usd(oa['whisper_api_usd'])}** |
| Embeddings | `{oa['embedding_model']}` @ $0.02 / 1M tokens | **{_fmt_usd(oa['embed_api_usd'])}** |
| **Total API estimado** | | **{_fmt_usd(oa['total_api_usd'])}** |
| Chunks | | {oa['total_chunks']:,} |
| Tokens ≈ | | {oa['total_tokens_approx']:,} |
| Dimensiones vector | | {oa['embedding_dims']} |
| Almacenamiento vectores (≈) | float32 + overhead | {oa['vector_storage_mb']} MB |

### Lectura

- El coste de **embeddings es casi despreciable** frente a la transcripción.
- El cuello de botella económico y de tiempo en cloud es el **ASR** (~{dur_min:.0f} minutos de audio).
- Alternativa más barata de ASR cloud: `gpt-4o-mini-transcribe` (~$0.003/min) ≈ la mitad del coste Whisper.

Notas:
{chr(10).join('- ' + n for n in oa['notes'])}

## 4. Escenario B — Infraestructura universidad (vLLM USFQ)

| Concepto | Supuesto | Resultado |
|---|---|---|
| ASR GPU-hours | factor tiempo-real ×0.25 | **{us['asr_gpu_hours']} h** |
| Embed GPU-hours | ~80 chunks/s (`{us['embedding_model']}`) | **{us['embed_gpu_hours']} h** |
| **Total GPU-hours** | | **{us['total_gpu_hours']} h** |
| Energía | 300 W × $0.12/kWh | **{us['energy_kwh']} kWh ≈ {_fmt_usd(us['energy_usd'])}** |
| Coste API | | **$0.00** |
| Chunks / dims | | {us['total_chunks']:,} / {us['embedding_dims']} |
| Almacenamiento vectores (≈) | | {us['vector_storage_mb']} MB |

### Lectura

- En on-prem el coste variable visible es **tiempo de GPU + energía**; la amortización
  del servidor (no modelada aquí) suele dominar el TCO anual.
- Los embeddings con `bge-m3` tardan **segundos**, no horas: el trabajo pesado sigue
  siendo el ASR de ~{dur_min/60:.1f} h de clase.
- Perfil ya definido en `src/llm/registry.py` → `vllm_usfq`
  (`EMBEDDING_BASE_URL` en `.env`).

Notas:
{chr(10).join('- ' + n for n in us['notes'])}

## 5. Comparativa

| Dimensión | OpenAI cloud | Universidad (vLLM) |
|---|---|---|
| Coste variable API | {_fmt_usd(oa['total_api_usd'])} | $0 |
| Coste variable energía | ~$0 (incluido en API) | {_fmt_usd(us['energy_usd'])} |
| GPU-hours estimadas | N/A (managed) | {us['total_gpu_hours']} h |
| Modelo embedding | `{oa['embedding_model']}` ({oa['embedding_dims']}d) | `{us['embedding_model']}` ({us['embedding_dims']}d) |
| Datos salen del campus | Sí (audio + texto a OpenAI) | No (procesamiento interno) |
| Dominante del coste | ASR Whisper | ASR GPU |

**Conclusión operativa:** para este módulo, **generar embeddings no es el driver de coste**;
lo es convertir ~{dur_min/60:.1f} h de vídeo a texto. Elegir OpenAI vs USFQ debe basarse
en **privacidad del material docente**, latencia/VPN al cluster y presupuesto de GPU,
no en el precio del embedder.

## 6. Pipeline implementado (sin ejecutar carga)

```
contabilidadFinaciera/**/{{*.pdf,*.mp4}}
        │
        ▼
src/ingestion/extractors/pdf.py     → texto PDF (pypdf)
src/ingestion/extractors/video.py   → audio (ffmpeg) → Whisper / endpoint USFQ
        │
        ▼
storage/extracted/<modulo>/*.txt    (solo si dry_run=False)
        │
        ▼
Document(status=pending) + POST /knowledge/ingest   ← NO ejecutado en esta métrica
        │
        ▼
mysql_pipeline.indexar_documento → chunks + chunk_embeddings
```

Comandos:

```bash
# Solo métricas (recomendado antes de cualquier carga)
python scripts/estimate_module_ingest.py contabilidadFinaciera --write-doc

# Extraer/transcribir a disco SIN embeber (requiere ffmpeg + API/ASR)
python scripts/estimate_module_ingest.py contabilidadFinaciera --extract

# Commit a MySQL + embeddings: usar API / Streamlit o module_media.commit_extracted_a_mysql
# con indexar=True cuando se quieran las métricas reales de una corrida.
```

## 7. Variables de entorno relevantes

| Variable | Uso |
|---|---|
| `LLM_PROFILE` | `cloud_openai` \| `vllm_usfq` |
| `OPENAI_API_KEY` | Embeddings + Whisper cloud |
| `EMBEDDING_MODEL` / `EMBEDDING_BASE_URL` | Override embeddings |
| `WHISPER_PROVIDER` | `openai` o `openai_compatible` |
| `WHISPER_BASE_URL` | ASR universidad (compatible OpenAI) |
| `WHISPER_MODEL` | p. ej. `whisper-1` |

## 8. Cómo reproducir estas cifras

```bash
python scripts/estimate_module_ingest.py contabilidadFinaciera --write-doc
```

Cualquier cambio de inventario (nuevos vídeos/PDF) invalida este informe; vuelve a
ejecutar el script para refrescar métricas.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "modulo",
        nargs="?",
        default="contabilidadFinaciera",
        help="Ruta o nombre del módulo bajo la raíz del repo",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Ruta del JSON de métricas",
    )
    parser.add_argument(
        "--write-doc",
        action="store_true",
        help="Escribe docs/costo-computacional-embeddings-<modulo>.md",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Ejecuta extracción/transcripción a storage/extracted (SIN embeddings)",
    )
    parser.add_argument(
        "--indice",
        default="apuntes",
        choices=["apuntes", "examenes", "rubricas", "curriculo"],
    )
    args = parser.parse_args()

    ruta = resolver_ruta_modulo(args.modulo)
    print(f"Módulo: {ruta}")

    if args.extract:
        print("Extrayendo medios (ASR real). No se generan embeddings.")
        result = preparar_modulo(ruta, dry_run=False, indice=args.indice)
        print(json.dumps({"out_dir": result["out_dir"], "n": len(result["extracciones"])}, indent=2))
        data = result["estimacion"]
    else:
        data = estimar_coste_modulo(ruta)

    json_path = guardar_informe_estimacion(ruta, destino=args.json_out)
    print(f"JSON: {json_path}")

    oa = data["cloud_openai"]
    us = data["vllm_usfq"]
    print(
        f"OpenAI total API ≈ {_fmt_usd(oa['total_api_usd'])} "
        f"(whisper {_fmt_usd(oa['whisper_api_usd'])} + embed {_fmt_usd(oa['embed_api_usd'])})"
    )
    print(
        f"USFQ ≈ {us['total_gpu_hours']} GPU-h · energía {_fmt_usd(us['energy_usd'])} · "
        f"chunks {oa['total_chunks']}"
    )

    if args.write_doc:
        doc_path = ROOT / "docs" / f"costo-computacional-embeddings-{ruta.name}.md"
        doc_path.write_text(_render_markdown(ruta.name, data), encoding="utf-8")
        print(f"Documento: {doc_path}")


if __name__ == "__main__":
    main()
