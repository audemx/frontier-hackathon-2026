#!/usr/bin/env bash
# Script para regenerar el pipeline con el código corregido
set -e

echo "========================================="
echo "REGENERACIÓN DE PIPELINE - REMEDIACIÓN PII"
echo "========================================="
echo ""

# Activar entorno virtual
if [ -d ".venv" ]; then
    echo "✓ Activando entorno virtual..."
    source .venv/bin/activate
else
    echo "❌ Error: No se encontró el entorno virtual .venv"
    exit 1
fi

# Paso 1: Borrar base de datos antigua
echo ""
echo "Paso 1: Limpiando base de datos antigua..."
if [ -f "data/entity_map.db" ]; then
    rm -f data/entity_map.db
    echo "✓ Base de datos eliminada"
else
    echo "✓ No había base de datos previa"
fi

# Paso 2: Borrar outputs anteriores
echo ""
echo "Paso 2: Limpiando outputs anteriores..."
if [ -d "output" ]; then
    rm -rf output/*.jsonl output/*.json
    echo "✓ Outputs eliminados"
fi

# Paso 3: Verificar modo de ejecución
echo ""
echo "Paso 3: Seleccionar fuente de datos..."
echo "  [1] Dataset de muestra local (sample/)"
echo "  [2] Dataset completo vía API remota"
read -p "Seleccione opción (1 o 2): " opcion

if [ "$opcion" == "1" ]; then
    echo ""
    echo "Ejecutando pipeline con dataset de muestra..."
    python3 << 'EOF'
from src.pipeline import run_pipeline
from pathlib import Path
import time

start = time.time()
result = run_pipeline(sample_dir=Path("sample"))
elapsed = time.time() - start

print("\n" + "="*50)
print("PIPELINE COMPLETADO")
print("="*50)
print(f"Chats procesados:  {result['chats']}")
print(f"Docs procesados:   {result['docs']}")
print(f"Tables procesadas: {result['tables']}")
print(f"Tiempo total:      {elapsed:.2f}s")
print("="*50)
EOF

elif [ "$opcion" == "2" ]; then
    echo ""
    read -p "Ingrese URL de la API de sources: " sources_url
    read -p "Ingrese token de autenticación: " token
    
    echo ""
    echo "Ejecutando pipeline con dataset remoto..."
    python3 << EOF
from src.pipeline import run_pipeline
import time

start = time.time()
result = run_pipeline(
    sources_url="${sources_url}",
    token="${token}"
)
elapsed = time.time() - start

print("\n" + "="*50)
print("PIPELINE COMPLETADO")
print("="*50)
print(f"Chats procesados:  {result['chats']}")
print(f"Docs procesados:   {result['docs']}")
print(f"Tables procesadas: {result['tables']}")
print(f"Tiempo total:      {elapsed:.2f}s")
print("="*50)
EOF

else
    echo "❌ Opción inválida"
    exit 1
fi

# Paso 4: Validar fugas localmente
echo ""
echo "Paso 4: Validando fugas de PII..."
python3 analyze_all_leaks.py

# Paso 5: Verificar colisiones de seudónimos
echo ""
echo "Paso 5: Verificando colisiones de seudónimos..."
python3 << 'EOF'
import json
import unicodedata
import re

def strip_accents(s):
    return ''.join(
        c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn'
    )

with open('output/entities.json') as f:
    data = json.load(f)

# Recopilar todos los originales
all_orig_tokens = set()
for e in data['entities']:
    if e.get('kept'):
        continue
    for orig in e.get('originals', []):
        tokens = strip_accents(orig.lower()).split()
        all_orig_tokens.update(tokens)

# Verificar colisiones en seudónimos
collisions = []
for e in data['entities']:
    if e.get('kept'):
        continue
    pseud = e.get('pseudonyms', {}).get('name', '')
    if pseud:
        tokens = strip_accents(pseud.lower()).split()
        for token in tokens:
            if token in all_orig_tokens:
                collisions.append((e['entity_id'], pseud, token))

if collisions:
    print(f'❌ Colisiones encontradas: {len(collisions)}')
    for eid, pseud, token in collisions[:10]:
        print(f'  {eid}: "{pseud}" contiene token "{token}" que es PII')
else:
    print('✓ No se encontraron colisiones de seudónimos')
EOF

echo ""
echo "========================================="
echo "REGENERACIÓN COMPLETADA"
echo "========================================="
echo ""
echo "Archivos generados:"
echo "  - output/chats.jsonl"
echo "  - output/docs.jsonl"
echo "  - output/tables.jsonl"
echo "  - output/entities.json"
echo "  - data/entity_map.db"
echo ""
echo "Siguiente paso:"
echo "  cd frontier-reto-1"
echo "  node validar.mjs ../output"
echo ""
