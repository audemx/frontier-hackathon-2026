# Contexto y Rol

Eres el Lead AI Engineer y Backend Architect para el equipo en el **Frontier Hackathon 2026**, construyendo la solución para el **Reto 1: Kipu Pay Fintech Data Anonymization**. 

Tu objetivo es implementar y completar el sistema completo de anonimización en Python bajo la estructura de directorios existente, asegurando cumplimiento estricto con la rúbrica oficial:
- **Privacidad / Prevención de Fugas (45%)**
- **Utilidad y Preservación de Negocio (35%)**
- **Consistencia Global y Resolución de Entidades (20%)**

Lee detenidamente la documentación del proyecto antes de escribir código:
- `docs/project.md` y `docs/system_design.md`
- `frontier-reto-1/ENUNCIADO.md` y `frontier-reto-1/api/participante.openapi.yaml`
- Los datos y salidas esperadas en `sample/`

---

## Estructura del Proyecto Actual
- `src/config.py`: Configuración de entorno y cliente OpenRouter.
- `src/pipeline.py`: Motor de ingestión, limpieza con Regex (anti-evasión de spam), extracción contextual con LLM (OpenRouter / Gemini Flash), y resolución de entidades con SQLite persistente (`data/entity_map.db`).
- `src/agent.py`: Orquestador de llamadas al LLM para análisis de texto complejo y generalización de cuasi-identificadores (barrio + ocupación + año).
- `src/main.py`: Aplicación FastAPI que implementa todos los endpoints del contrato OpenAPI participante (`/health`, `/run`, `/run/{job_id}`, `/output/{archivo}`, `/anonymize`, `/entities`).
- `run.sh`: Script para levantar el servidor de producción (uvicorn).

---

## Tareas Específicas a Implementar

### 1. `src/config.py`
- Cargar variables de entorno con `python-dotenv`.
- Configurar cliente OpenAI compatible con OpenRouter (modelo por defecto: `openai/gpt-4o-mini`).
- Definir rutas base para `data/`, `output/` y `sample/`.

### 2. `src/pipeline.py` & `src/agent.py` (El Motor de 3 Capas)
- **Capa 1 (Regex Anti-Evasion):** Detección robusta de correos estándar y deletreados (*"usuario AT domain PUNTO com"*), cédulas colombianas, pasaportes, teléfonos y placas.
- **Capa 2 (LLM Contextual):** Extracción de nombres propios, apodos y desambiguación de homónimos (dos personas distintas con el mismo nombre deben recibir seudónimos distintos basados en sus huellas únicas de ID).
- **Capa 3 (Persistencia SQLite en `data/entity_map.db`):** Almacenar y consultar el mapeo determinístico `[unique_entity_fingerprint] -> [synthetic_profile]` para garantizar el 20% de consistencia global en Slack, tablas CSV/XML y metadatos de PDF.
- **Generación de los 4 archivos obligatorios en `output/`:**
  1. `chats.jsonl`
  2. `docs.jsonl` (preservando todas las llaves de metadatos originales)
  3. `tables.jsonl` (preservando columnas y llaves como `clientes:CL-...`)
  4. `entities.json` (diccionario de auditoría con `kept: true` para marcas/figuras públicas como Bancolombia o Shakira).

### 3. `src/main.py` (FastAPI Service)
Implementa estrictamente los endpoints del contrato OpenAPI:
- `GET /health`
- `POST /run` (Ejecución asíncrona del pipeline completo consultando el API de fuentes con token Bearer, generando `job_id`).
- `GET /run/{job_id}`
- `GET /output/{archivo}` (Con protección estricta contra path traversal, sirviendo solo los 4 archivos permitidos).
- `POST /anonymize` (Procesa lotes de hasta 50 registros en vivo en menos de 60 segundos manteniendo consistencia con SQLite).
- `GET /entities` (Devuelve el diccionario completo para el jurado).

### 4. `run.sh`
- Asegurar que levante el servidor FastAPI usando Uvicorn correctamente en `0.0.0.0:8000` (o el puerto configurado por entorno).

---

## Validación y Verificación
Una vez implementado el código, asegúrate de que el pipeline genere los archivos correctos y que pasen sin errores de esquema frente a la muestra y el validador (`node validar.mjs`).

Por favor, procede a escribir y completar la implementación robusta de cada módulo en `src/`.