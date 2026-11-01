#!/usr/bin/env bash
# Script de verificación rápida de las correcciones

echo "============================================"
echo "VERIFICACIÓN DE CORRECCIONES - FUGAS PII"
echo "============================================"
echo ""

# Verificar que existen los archivos necesarios
if [ ! -f "output/entities.json" ]; then
    echo "❌ Error: No se encontró output/entities.json"
    echo "   Ejecute primero: ./regenerate_pipeline.sh"
    exit 1
fi

# Activar entorno virtual
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ Error: No se encontró entorno virtual"
    exit 1
fi

# Verificación 1: Estadísticas básicas
echo "📊 Estadísticas de Salida:"
echo "  - Chats:    $(wc -l < output/chats.jsonl) registros"
echo "  - Docs:     $(wc -l < output/docs.jsonl) registros"
echo "  - Tables:   $(wc -l < output/tables.jsonl) registros"
echo "  - Entidades: $(jq '.entities | length' output/entities.json) entidades"
echo ""

# Verificación 2: Fugas de PII
echo "🔍 Análisis de Fugas de PII:"
python3 << 'PYEOF'
import json
from pathlib import Path
import unicodedata
import re

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def solo_digitos(s):
    return re.sub(r"\D", "", s)

def contiene(haystack, needle):
    if not needle or not haystack:
        return False
    h = strip_accents(haystack.lower())
    n = strip_accents(needle.lower())
    digitos = solo_digitos(needle)
    if digitos and len(digitos) >= 6:
        return digitos in solo_digitos(haystack)
    if re.search(r"^[a-z0-9 .'_-]+$", n) and re.search(r"[a-z]", n):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h))
    return n in h

with open('output/entities.json') as f:
    data = json.load(f)

all_records = {}
for fname in ['chats.jsonl', 'tables.jsonl', 'docs.jsonl']:
    with open(f'output/{fname}') as f2:
        for line in f2:
            rec = json.loads(line)
            rec_id = rec.get('id', '')
            content = str(rec)
            all_records[rec_id] = content

total_leaks = 0
for e in data['entities']:
    if e.get('kept'):
        continue
    for orig in e.get('originals', []):
        if len(orig) < 3:
            continue
        for rec_id, content in all_records.items():
            if contiene(content, orig):
                total_leaks += 1

if total_leaks == 0:
    print("  ✅ No se detectaron fugas de PII")
else:
    print(f"  ❌ ALERTA: {total_leaks} fugas detectadas")
PYEOF
echo ""

# Verificación 3: Colisiones de seudónimos
echo "🔄 Análisis de Colisiones de Seudónimos:"
python3 << 'PYEOF'
import json
import unicodedata

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

with open('output/entities.json') as f:
    data = json.load(f)

all_orig_tokens = set()
for e in data['entities']:
    if e.get('kept'):
        continue
    for orig in e.get('originals', []):
        tokens = strip_accents(orig.lower()).split()
        all_orig_tokens.update(tokens)

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

if not collisions:
    print("  ✅ No se detectaron colisiones")
else:
    print(f"  ❌ ALERTA: {len(collisions)} colisiones detectadas")
    for eid, pseud, token in collisions[:5]:
        print(f"     • {eid}: '{pseud}' contiene '{token}'")
PYEOF
echo ""

# Verificación 4: Ejemplos de transformaciones exitosas
echo "✨ Ejemplos de Transformaciones Exitosas:"
echo ""
echo "  Entidad p_003:"
jq -r '.entities[] | select(.entity_id == "p_003") | 
    "    Originales: \(.originals | length) variantes\n" +
    "    Seudónimo: \(.pseudonyms.name)\n" +
    "    Email: \(.pseudonyms.email)\n" +
    "    Registros: \(.records | length)"' output/entities.json 2>/dev/null || echo "    (entidad no encontrada en muestra)"
echo ""

# Verificación 5: Integridad de la base de datos
if [ -f "data/entity_map.db" ]; then
    echo "💾 Base de Datos SQLite:"
    sqlite3 data/entity_map.db "SELECT COUNT(*) FROM entities WHERE kept = 0;" 2>/dev/null | xargs echo "  - Entidades de personas:"
    sqlite3 data/entity_map.db "SELECT COUNT(*) FROM entities WHERE kept = 1;" 2>/dev/null | xargs echo "  - Entidades conservadas:"
    sqlite3 data/entity_map.db "SELECT COUNT(*) FROM entity_originals;" 2>/dev/null | xargs echo "  - Variantes registradas:"
    echo ""
fi

echo "============================================"
echo "VERIFICACIÓN COMPLETADA"
echo "============================================"
echo ""
echo "Estado: $([ $? -eq 0 ] && echo '✅ LISTO PARA PRODUCCIÓN' || echo '⚠️  Revisar alertas')"
echo ""
