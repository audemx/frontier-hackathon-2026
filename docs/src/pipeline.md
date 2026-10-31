# Documentación del Pipeline de Anonimización (Kipu Pay)

El pipeline implementa una arquitectura robusta orientada a garantizar la privacidad de los datos financieros y personales, cumpliendo con los estándares de evaluación de Frontier Hackathon 2026.

## Arquitectura de 3 Capas

1. **Capa 1: Regex Anti-Evasión**
   - Intercepción de correos electrónicos deletreados o camuflados (ej. *arroba*, *punto*).
   - Traducción segura de menciones de Slack (`<@UID>`).
   - Saneamiento de nombres de archivos adjuntos y metadatos.

2. **Capa 2: Extracción Contextual y Generalización**
   - Disambiguación de homónimos y control de alcance para nombres de pila basado en la participación dentro de hilos específicos de Slack.
   - Generalización algorítmica de cuasi-identificadores (ocupaciones, barrios y años de nacimiento).

3. **Capa 3: Persistencia SQLite y Coherencia Global**
   - Base de datos local persistente (`data/entity_map.db`) para mantener una correspondencia biunívoca entre identidades reales y perfiles sintéticos.
   - Protección estricta de marcas, instituciones financieras y figuras públicas (`kept = 1`).
   - Auditoría de salida mediante la función de contención (`contiene`) para asegurar la validez absoluta frente a `validar.mjs`.

## Funciones Clave del Módulo (`src/pipeline.py`)
- **`EntityManager`**: Administra la persistencia SQLite, la creación de perfiles sintéticos sin colisiones y el registro de originales.
- **`AnonymizationEngine`**: Motor principal de sustitución de texto plano y metadatos con expresiones regulares compiladas por longitud.
- **`run_pipeline`**: Orquestador masivo encargado de la ingesta, procesamiento y exportación de los archivos `chats.jsonl`, `docs.jsonl`, `tables.jsonl` y `entities.json`.
- **`anonymize_live_batch`**: Gestor de procesamiento síncrono en tiempo real para lotes individuales mediante API REST.