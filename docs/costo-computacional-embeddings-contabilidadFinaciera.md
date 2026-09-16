# Costo computacional de embeddings — módulo `contabilidadFinaciera`

**Generado (UTC):** 2026-09-16T02:49:00Z  
**Modo:** estimación en seco (sin ASR, sin embeddings, sin escritura en MySQL)  
**Script:** `scripts/estimate_module_ingest.py`  
**Ruta inventariada:** `/Users/peluchito/Desktop/Orquestacion-Agentes/contabilidadFinaciera`

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
| PDFs | 1 |
| Vídeos | 8 |
| Textos | 0 |
| Peso total | 2.43 GB |
| Duración vídeo | **912.0 min** (15.20 h) |
| Chars PDF (capa de texto) | 194,253 |

### Detalle por fuente

| Archivo | Tipo | Chars (est.) | Tokens (≈) | Chunks (≈) | Duración |
|---|---|---:|---:|---:|---|
| `GMT20251008-003001_Recording_1686x768.mp4` | video | 79,223 | 19,806 | 94 | 110.0 min |
| `GMT20251015-000859_Recording_1686x768.mp4` | video | 83,983 | 20,996 | 99 | 116.6 min |
| `GMT20251022-001105_Recording_1686x768.mp4` | video | 88,410 | 22,103 | 104 | 122.8 min |
| `GMT20251029-000743_Recording_1686x768.mp4` | video | 81,637 | 20,410 | 96 | 113.4 min |
| `GMT20251115-000945_Recording_1686x728.mp4` | video | 83,137 | 20,785 | 98 | 115.5 min |
| `GMT20251119-001119_Recording_1686x768.mp4` | video | 81,446 | 20,362 | 96 | 113.1 min |
| `GMT20251122-001420_Recording_1686x768.mp4` | video | 83,593 | 20,899 | 99 | 116.1 min |
| `GMT20251126-000940_Recording_1686x768.mp4` | video | 75,197 | 18,800 | 89 | 104.4 min |
| `Guía didáctica.pdf` | pdf | 194,253 | 48,564 | 229 | — |

**Chunking alineado al pipeline:** `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)`  
(`src/ingestion/mysql_pipeline.py`).

**Transcripción de vídeo (dry-run):** densidad heurística
`CHARS_POR_MINUTO_ESTIMADOS = 720` (clase en español). El valor real saldrá del ASR.

## 3. Escenario A — OpenAI (cloud)

| Concepto | Modelo / tarifa | Resultado |
|---|---|---|
| ASR | `whisper-1` @ $0.006 / min | **$5.4719** |
| Embeddings | `text-embedding-3-small` @ $0.02 / 1M tokens | **$0.004255** |
| **Total API estimado** | | **$5.4762** |
| Chunks | | 1,004 |
| Tokens ≈ | | 212,725 |
| Dimensiones vector | | 1536 |
| Almacenamiento vectores (≈) | float32 + overhead | 7.648 MB |

### Lectura

- El coste de **embeddings es casi despreciable** frente a la transcripción.
- El cuello de botella económico y de tiempo en cloud es el **ASR** (~912 minutos de audio).
- Alternativa más barata de ASR cloud: `gpt-4o-mini-transcribe` (~$0.003/min) ≈ la mitad del coste Whisper.

Notas:
- Embeddings API: $0.02/1M tokens (text-embedding-3-small).
- ASR API: $0.006/min (whisper-1 o equivalente).
- No incluye coste de chat/razonamiento de agentes tras el ingest.
- Tokens aproximados (chars/4); la factura real usa el tokenizer de OpenAI.

## 4. Escenario B — Infraestructura universidad (vLLM USFQ)

| Concepto | Supuesto | Resultado |
|---|---|---|
| ASR GPU-hours | factor tiempo-real ×0.25 | **3.7999 h** |
| Embed GPU-hours | ~80 chunks/s (`BAAI/bge-m3`) | **0.003486 h** |
| **Total GPU-hours** | | **3.8034 h** |
| Energía | 300 W × $0.12/kWh | **1.141 kWh ≈ $0.1369** |
| Coste API | | **$0.00** |
| Chunks / dims | | 1,004 / 1024 |
| Almacenamiento vectores (≈) | | 5.098 MB |

### Lectura

- En on-prem el coste variable visible es **tiempo de GPU + energía**; la amortización
  del servidor (no modelada aquí) suele dominar el TCO anual.
- Los embeddings con `bge-m3` tardan **segundos**, no horas: el trabajo pesado sigue
  siendo el ASR de ~15.2 h de clase.
- Perfil ya definido en `src/llm/registry.py` → `vllm_usfq`
  (`EMBEDDING_BASE_URL` en `.env`).

Notas:
- Sin coste API de OpenAI: ASR + embeddings en infraestructura universidad.
- ASR: factor tiempo-real ×0.25 (faster-whisper / GPU).
- Embeddings: ~80.0 chunks/s en GPU (BAAI/bge-m3).
- Energía ilustrativa: 300.0 W × $0.12/kWh (sin amortización GPU).
- Amortización de servidor/GPU y ops no incluidas; suelen dominar el TCO.

## 5. Comparativa

| Dimensión | OpenAI cloud | Universidad (vLLM) |
|---|---|---|
| Coste variable API | $5.4762 | $0 |
| Coste variable energía | ~$0 (incluido en API) | $0.1369 |
| GPU-hours estimadas | N/A (managed) | 3.8034 h |
| Modelo embedding | `text-embedding-3-small` (1536d) | `BAAI/bge-m3` (1024d) |
| Datos salen del campus | Sí (audio + texto a OpenAI) | No (procesamiento interno) |
| Dominante del coste | ASR Whisper | ASR GPU |

**Conclusión operativa:** para este módulo, **generar embeddings no es el driver de coste**;
lo es convertir ~15.2 h de vídeo a texto. Elegir OpenAI vs USFQ debe basarse
en **privacidad del material docente**, latencia/VPN al cluster y presupuesto de GPU,
no en el precio del embedder.

## 6. Pipeline implementado (sin ejecutar carga)

```
contabilidadFinaciera/**/{*.pdf,*.mp4}
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
