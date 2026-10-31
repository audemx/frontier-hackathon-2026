# Development Logs

## System Design

* [10:30] - Committing system design, project brief, logs.
* [11:00] - Analyzing the problem statement and outlining key requirements:
    * Entity Fingerprint.
    * Not explicit ID.
    * Handle new entities.

* [12:00] - Commiting system design and init.sh run.
    * arch: proyect, system-design and init.sh run.

* [1:30] - Prompting and running `docs/prompt_design.md`.
    * Implemented `src/config.py` with environment loader and OpenRouter client.
    * Implemented `src/agent.py` for contextual analysis and quasi-identifier breaking.
    * Implemented `src/pipeline.py` with 3-layer anonymization engine and SQLite persistence.
    * Implemented `src/main.py` with full OpenAPI contract endpoints (`/health`, `/run`, `/run/{id}`, `/output/{file}`, `/anonymize`, `/entities`).
    * Configured `run.sh` with uvicorn server launcher.
    * Validated on sample dataset: passed 13/13 tests and 0 errors on official `validar.mjs`.
    * Generated `DECISIONS.md` responding to the 3 official evaluation criteria.

* [2:30] - Validation: `node validar.mjs output/ --public fuentes/`.
* [2:35] - Run data exploration and system design tests.
    * Sample data exploration via `notebooks/exploracion.ipynb`.
    * System evaluation tests via `notebooks/test.ipynb`.
* [2:40] - Commit Changes
    * arch: src and notebooks test completed.

* [2:45] - Launch massive processing (POST /run).
    * `curl -X POST "http://localhost:8000/run" \
        -H "Content-Type: application/json" \
        -d '{
            "sources_url": "https://reto-pii-fuentes-production.up.railway.app/v1",
            "token": "TOKEN_DE_EQUIPO"
        }'`
    * Watching state via POST /run/{id}: 
        `curl -s http://localhost:8000/run/JOB_ID | json_pp`
    * Downloading completed.

* [3:20] - Run massive processing `node frontier-reto-1/validar.mjs output/ --public sample`.