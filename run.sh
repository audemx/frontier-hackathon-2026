#!/usr/bin/env bash
set -e

# Loads the environment if .venv exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Executes the main module inside a package named src as a script, forwarding any arguments passed to the shell wrapper ("$@") directly to Python.
python3 -m src.main "$@"