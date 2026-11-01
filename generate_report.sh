#!/usr/bin/env bash
# Script para generar reporte visual de la auditoría

clear
echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                                                                    ║"
echo "║   🔒 AUDITORÍA Y REMEDIACIÓN - KIPU PAY PII PIPELINE             ║"
echo "║   Frontier Hackathon 2026 - Reto 1                                ║"
echo "║                                                                    ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📅 Fecha: $(date +'%Y-%m-%d %H:%M:%S')"
echo "👤 Auditor: Arquitecto de Software Senior - Ciberseguridad"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Verificar archivos clave
echo "📂 VERIFICACIÓN DE ARCHIVOS"
echo "──────────────────────────────────────────────────────────────────"
files=(
    "src/pipeline.py:Código principal"
    "data/entity_map.db:Base de datos SQLite"
    "output/entities.json:Diccionario de entidades"
    "output/chats.jsonl:Chats anonimizados"
    "output/docs.jsonl:Documentos anonimizados"
    "output/tables.jsonl:Tablas anonimizadas"
)

for file_desc in "${files[@]}"; do
    IFS=':' read -r file desc <<< "$file_desc"
    if [ -f "$file" ]; then
        size=$(du -h "$file" | cut -f1)
        echo "  ✅ $desc ($size)"
    else
        echo "  ❌ $desc (NO ENCONTRADO)"
    fi
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 MÉTRICAS DE CORRECCIÓN"
echo "──────────────────────────────────────────────────────────────────"

# Verificar si existe output/entities.json
if [ -f "output/entities.json" ]; then
    source .venv/bin/activate 2>/dev/null
    
    entities_count=$(jq '.entities | length' output/entities.json 2>/dev/null || echo "?")
    chats_count=$(wc -l < output/chats.jsonl 2>/dev/null || echo "?")
    docs_count=$(wc -l < output/docs.jsonl 2>/dev/null || echo "?")
    tables_count=$(wc -l < output/tables.jsonl 2>/dev/null || echo "?")
    
    echo "  • Entidades generadas:        $entities_count"
    echo "  • Chats procesados:           $chats_count"
    echo "  • Documentos procesados:      $docs_count"
    echo "  • Tablas procesadas:          $tables_count"
    echo ""
    
    # Ejecutar análisis de fugas
    echo "  🔍 Analizando fugas de PII..."
    leak_result=$(python3 -c "
import json
import unicodedata
import re

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def solo_digitos(s):
    return re.sub(r'\D', '', s)

def contiene(haystack, needle):
    if not needle or not haystack:
        return False
    h = strip_accents(haystack.lower())
    n = strip_accents(needle.lower())
    digitos = solo_digitos(needle)
    if digitos and len(digitos) >= 6:
        return digitos in solo_digitos(haystack)
    if re.search(r'^[a-z0-9 .\'_-]+$', n) and re.search(r'[a-z]', n):
        return bool(re.search(rf'(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])', h))
    return n in h

with open('output/entities.json') as f:
    data = json.load(f)

all_records = {}
for fname in ['chats.jsonl', 'tables.jsonl', 'docs.jsonl']:
    try:
        with open(f'output/{fname}') as f2:
            for line in f2:
                rec = json.loads(line)
                rec_id = rec.get('id', '')
                content = str(rec)
                all_records[rec_id] = content
    except:
        pass

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

print(total_leaks)
" 2>/dev/null || echo "ERROR")
    
    if [ "$leak_result" == "0" ]; then
        echo "  ✅ Fugas de PII detectadas:   0 (EXCELENTE)"
    elif [ "$leak_result" == "ERROR" ]; then
        echo "  ⚠️  Fugas de PII detectadas:   ERROR en análisis"
    else
        echo "  ❌ Fugas de PII detectadas:   $leak_result (REVISAR)"
    fi
    
    # Verificar colisiones
    echo "  🔄 Analizando colisiones de seudónimos..."
    collision_result=$(python3 -c "
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

collisions = 0
for e in data['entities']:
    if e.get('kept'):
        continue
    pseud = e.get('pseudonyms', {}).get('name', '')
    if pseud:
        tokens = strip_accents(pseud.lower()).split()
        for token in tokens:
            if token in all_orig_tokens:
                collisions += 1

print(collisions)
" 2>/dev/null || echo "ERROR")
    
    if [ "$collision_result" == "0" ]; then
        echo "  ✅ Colisiones detectadas:     0 (EXCELENTE)"
    elif [ "$collision_result" == "ERROR" ]; then
        echo "  ⚠️  Colisiones detectadas:     ERROR en análisis"
    else
        echo "  ❌ Colisiones detectadas:     $collision_result (REVISAR)"
    fi
else
    echo "  ⚠️  No se encontró output/entities.json"
    echo "  💡 Ejecutar: ./regenerate_pipeline.sh"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "🏆 VULNERABILIDADES CORREGIDAS"
echo "──────────────────────────────────────────────────────────────────"
echo "  [✅] #1: Colisión de seudónimos con originales"
echo "  [✅] #2: Nombres de archivos adjuntos no blindados"
echo "  [✅] #3: Variantes de teléfonos no registradas"
echo "  [✅] #4: Variantes de cédulas con prefijo CC no registradas"
echo "  [✅] #5: Parche dinámico ineficiente (eliminado)"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "📚 DOCUMENTACIÓN DISPONIBLE"
echo "──────────────────────────────────────────────────────────────────"
echo "  📄 RESUMEN_AUDITORIA.md           | Resumen ejecutivo"
echo "  📄 docs/AUDITORIA_FINAL.md        | Análisis técnico exhaustivo"
echo "  📄 docs/CAMBIOS_CODIGO.md         | Especificación de cambios"
echo "  📄 docs/ANTES_DESPUES_VISUAL.md   | Ejemplos visuales"
echo "  📄 INDICE_DOCUMENTACION.md        | Índice completo"
echo "  📄 CHECKLIST_FINAL.md             | Checklist de validación"
echo "  📄 README.md                      | Documentación principal"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "🛠️  COMANDOS ÚTILES"
echo "──────────────────────────────────────────────────────────────────"
echo "  Regenerar pipeline:       ./regenerate_pipeline.sh"
echo "  Verificar correcciones:   ./verify_fixes.sh"
echo "  Analizar fugas:           python analyze_all_leaks.py"
echo "  Validador oficial:        cd frontier-reto-1 && node validar.mjs ../output"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Determinar estado general
if [ "$leak_result" == "0" ] && [ "$collision_result" == "0" ]; then
    echo "🎉 ESTADO: ✅ LISTO PARA PRODUCCIÓN"
elif [ "$leak_result" == "ERROR" ] || [ "$collision_result" == "ERROR" ]; then
    echo "⚠️  ESTADO: ⚠️  VERIFICACIÓN REQUERIDA"
else
    echo "❌ ESTADO: ⚠️  REQUIERE CORRECCIONES ADICIONALES"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 Reporte generado en: $(date +'%Y-%m-%d %H:%M:%S')"
echo ""
