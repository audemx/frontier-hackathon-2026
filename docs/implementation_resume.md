# Resumen de Módulos Implementados

## `src/config.py`:

Carga segura de variables de entorno con python-dotenv (OPENROUTER_API_KEY, FUENTES_URL, FUENTES_TOKEN, DEFAULT_MODEL).
Rutas canónicas para data/, output/, sample/ y la base SQLite data/entity_map.db.
Cliente OpenAI compatible con OpenRouter configurado para openai/gpt-4o-mini.

## `src/agent.py`:

Rompimiento de Cuasi-Identificadores (generalize_quasi_identifiers): Detección y generalización de triplas compuestas (barrio + ocupación + año) convirtiendo ocupaciones específicas a sectores (fotógrafa → profesional de las industrias creativas), barrios a ciudades (Granada → Cali) y años a rangos (hace unos años).
Desambiguación de Homónimos (disambiguate_homonym): Resolución de contexto de personas con nombres idénticos mediante IDs estructurales, cédula, correo o inferencia contextual LLM.

## `src/pipeline.py` (Motor de 3 Capas):

* Capa 1 (Regex Anti-Evasión): Detección y normalización de correos deletreados ("usuario arroba domain punto com", [at], (punto)), cédulas colombianas (con y sin puntos), celulares (+57 3xx), placas vehiculares (GTD596) y menciones de Slack (<@UID>).

* Capa 2 (Mapeo Contextual y Fronteras Alfanuméricas): Detección con límites (?<![a-zA-Z0-9]) y (?![a-zA-Z0-9]) para captura precisa en textos, notas y nombres de archivos adjuntos (extracto_manuela_castano_julio.pdf → extracto_sofia_elena_zambrano_julio.pdf).

* Capa 3 (Persistencia SQLite): Mapeo determinístico [huella_entidad] -> [perfil_sintetico], garantizando unicidad y consistencia global entre corridas y pruebas en vivo.

Generación de los 4 Archivos Obligatorios en output/:
chats.jsonl: Formato Slack normalizado (id, thread_id, author con seudónimo, text, attachments).
docs.jsonl: Preserva todas las llaves de metadatos originales (title, author, fecha, etc.) y cuerpos procesados en Markdown/HTML/PDF.
tables.jsonl: Preserva llaves (clientes:CL-..., transacciones:TX-..., pqrs:PQR-..., empleados:KP-...) y columnas originales.
entities.json: Diccionario para el jurado con kept: true para entidades conservadas (Bancolombia, Nequi, Superfinanciera, etc.) y campos de seudónimos validados contra registros reales.

## `src/main.py` (Servicio FastAPI):

* GET /health (y /v1/health)
* POST /run (y /v1/run): Acepta sources_url y token, ejecutando el pipeline de forma asíncrona mediante BackgroundTasks y devolviendo job_id.
* GET /run/{job_id}: Monitoreo en tiempo real del estado (queued, running, done, failed), conteos de registros y tiempos de ejecución.
* GET /output/{archivo}: Descarga con protección estricta contra path traversal, sirviendo únicamente los 4 archivos permitidos.
* POST /anonymize: Procesamiento en vivo de lotes de hasta 50 registros en menos de 1 segundo manteniendo consistencia con SQLite.
* GET /entities: Entrega el diccionario de auditoría completo.

## `run.sh`:

Script ejecutable que activa .venv y levanta Uvicorn en 0.0.0.0:8000 (o el puerto configurado dinámicamente en $PORT).

## `DECISIONS.md`:

Documento oficial de decisiones respondiendo las 3 preguntas de la rúbrica (definición de PII, elementos conservados y análisis de costos/tiempos).