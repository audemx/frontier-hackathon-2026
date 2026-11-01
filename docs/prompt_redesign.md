# Rol y Contexto
Eres un Arquitecto de Software Senior especializado en Ciberseguridad, Privacidad de Datos y APIs de Alto Rendimiento en FastAPI. Estás auditando el proyecto **Kipu Pay PII Anonymization Pipeline** (Frontier Hackathon 2026 - Reto 1).

El objetivo del proyecto es un pipeline robusto de anonimización de PII en 3 capas (Regex anti-evasión, extracción contextual y persistencia determinista en SQLite) que cumpla estrictamente con el contrato OpenAPI (`participante.openapi.yaml`) y supere el script de validación de los jueces (`validar.mjs`).

---

# Estructura del Repositorio a Auditar
- `src/`: Contiene la lógica central (`pipeline.py`, `main.py`, `agent.py`, `config.py`)
- `docs/`: Documentación técnica del sistema (`docs/src/pipeline.md`, `docs/DECISIONS.md`, `docs/system-design.md`, `docs/adrs/`)
- `data/entity_map.db`: Base de datos SQLite persistente para mapeo determinista de entidades.
- `frontier-reto-1/validar.mjs`: Script oficial de validación de fugas y estructura.

---

# Observaciones Clave e Incidencias Detectadas (Contexto Crítico)
Durante las pruebas de integración se presentaron los siguientes problemas críticos que deben ser auditados y corregidos en el código:

1. **Incidente INC-PII-01 (Fusión de Págalo):** El sistema fue actualizado para integrar nuevas fuentes de datos sin destruir la base de datos SQLite (`data/entity_map.db`). Las entidades preexistentes DEBEN conservar exactamente sus seudónimos anteriores, mientras que las nuevas entidades deben recibir seudónimos únicos.
2. **Fugas de PII en Tablas vs Textos Libres:** El motor de reemplazo basado en regex y el parche dinámico funcionaban en textos libres (`chats`, `docs`), pero fallaban o dejaban escapar identificadores (cédulas con/sin puntos como `1.022.649.507`, teléfonos como `+57 350...` y nombres como `Camila` / `Verónica`) en las columnas estructuradas de las tablas (`clientes`, `empleados`, `pqrs`, `transacciones`).
3. **Normalización y Containment:** Las comparaciones de texto deben alinearse milimétricamente con la lógica de `validar.mjs` (manejo de acentos con `strip_accents`, caracteres confusibles y límites de palabras).
4. **Guardrail Anti-Fugas:** El método `validate_no_pii_leaks` detecta correctamente las fugas de PII en tiempo de ejecución, pero necesitamos asegurar que la cobertura de normalización de `EntityManager` y `AnonymizationEngine` no deje ningún resquicio sin registrar en `entity_originals`.

---

# Objetivos de la Revisión Exhaustiva

Por favor, realiza una auditoría línea por línea y análisis de coherencia enfocándote en:

1. **Coherencia Documental vs Código:** Revisa la carpeta `docs/` (especialmente `docs/src/pipeline.md` y `docs/DECISIONS.md`) y contrástala con la implementación actual en `src/pipeline.py` y `src/main.py`. Identifica desviaciones arquitectónicas.
2. **Robustez del Pipeline de Anonimización (`src/pipeline.py`):** 
   - Analiza cómo se procesan las tablas (`tables.jsonl`) frente a los documentos y chats.
   - Verifica si el registro de variantes en `EntityManager` cubre exhaustivamente mayúsculas, minúsculas, tildes y formatos numéricos (cédulas/teléfonos con y sin símbolos).
   - Audita el flujo de persistencia en SQLite para garantizar la estabilidad de seudónimos exigida por el incidente INC-PII-01.
3. **Plan de Remediación Definitivo:** Proporciona un diagnóstico claro de los puntos ciegos que causaron las 117 incidencias del validador y las correcciones exactas de código en Python para blindar el pipeline de forma definitiva.

Presenta tu informe estructurado, priorizando hallazgos críticos y fragmentos de código corregidos listos para producción.

Error reportado:
Tu salida no pasa el validador (117 problemas): entities[p_003] la forma original '+57 350 616 2589' sigue en la salida, p. ej. ['831677b8-b0ac-58b6-8c0d-13e502239e7f'] · entities[p_003] la forma original '1.022.649.507' sigue en la salida, p. ej. ['e468c591-8352-58b5-80fe-672cfc4469d8'] · entities[p_003] la forma original '1022649507' sigue en la salida, p. ej. ['e468c591-8352-58b5-80fe-672cfc4469d8'] · entities[p_003] la forma original '3506162589' sigue en la salida, p. ej. ['831677b8-b0ac-58b6-8c0d-13e502239e7f'] · entities[p_003] la forma original 'camila' sigue en la salida, p. ej. ['a7885c18-3e81-5b48-857a-da38dd8b442c', '12347139-6bc9-5eef-b445-b32a17248e88']