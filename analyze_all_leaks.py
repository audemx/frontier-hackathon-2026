#!/usr/bin/env python3
"""Script para analizar fugas de PII en TODAS las entidades."""

import json
import re
from pathlib import Path
import unicodedata

def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )

def norm_text(s: str) -> str:
    return strip_accents(s).lower()

def solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)

def contiene(haystack: str, needle: str) -> bool:
    """Evaluates text containment identically to validar.mjs."""
    if not needle or not haystack:
        return False
    digitos = solo_digitos(needle)
    if digitos and len(digitos) >= 6 and len(digitos) >= 0.6 * len(needle) and not re.search(r"[a-zA-Z]", needle):
        # Búsqueda de dígitos
        h_digits = solo_digitos(haystack)
        candidates = {digitos}
        if len(digitos) == 12 and digitos.startswith("57"):
            candidates.add(digitos[2:])
        for d in candidates:
            if d and re.search(rf"(?<!\d)(?:57)?{re.escape(d)}(?!\d)", h_digits):
                return True
        return False

    h = norm_text(haystack)
    n = norm_text(needle)
    if re.search(r"^[a-z0-9 .'_-]+$", n) and re.search(r"[a-z]", n):
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h):
            return True
        palabras = n.split()
        if len(palabras) >= 2 and all(len(w) >= 3 for w in palabras):
            pattern = r"(?<![a-z0-9])" + r"\s*".join(re.escape(w) for w in palabras) + r"(?![a-z0-9])"
            if re.search(pattern, h):
                return True
        return False
    return n in h

# Cargar entities.json
entities_path = Path("output/entities.json")
with open(entities_path) as f:
    entities_data = json.load(f)

print(f"Total de entidades: {len(entities_data['entities'])}")

# Cargar todos los archivos de salida
all_records = {}

# Chats
chats_path = Path("output/chats.jsonl")
with open(chats_path) as f:
    for line in f:
        rec = json.loads(line)
        record_id = rec.get("id", "")
        content_parts = []
        content_parts.append(rec.get("author", ""))
        content_parts.append(rec.get("text", ""))
        for att in rec.get("attachments", []):
            content_parts.append(att.get("filename", ""))
        all_records[record_id] = " | ".join(content_parts)

# Tables
tables_path = Path("output/tables.jsonl")
with open(tables_path) as f:
    for line in f:
        rec = json.loads(line)
        record_id = rec.get("id", "")
        content_parts = [str(v) for v in rec.get("columns", {}).values()]
        all_records[record_id] = " | ".join(content_parts)

# Docs
docs_path = Path("output/docs.jsonl")
with open(docs_path) as f:
    for line in f:
        rec = json.loads(line)
        record_id = rec.get("id", "")
        content_parts = [
            rec.get("filename", ""),
            rec.get("title", ""),
            rec.get("body", "")
        ]
        all_records[record_id] = " | ".join(content_parts)

print(f"Total de registros de salida: {len(all_records)}")

# Verificar fugas para cada entidad
total_leaks = 0
entities_with_leaks = []

for entity in entities_data["entities"]:
    eid = entity["entity_id"]
    if entity.get("kept"):
        continue  # Skip kept entities
    
    entity_leaks = []
    for orig in entity.get("originals", []):
        if len(orig) < 3:
            continue
        
        # Buscar en todos los registros
        for record_id, content in all_records.items():
            if contiene(content, orig):
                entity_leaks.append({
                    "entity": eid,
                    "original": orig,
                    "record_id": record_id,
                })
    
    if entity_leaks:
        total_leaks += len(entity_leaks)
        entities_with_leaks.append({
            "entity_id": eid,
            "leaks": entity_leaks,
            "pseudonym": entity.get("pseudonyms", {}).get("name", ""),
        })

print(f"\nFugas detectadas: {total_leaks}")
print(f"Entidades con fugas: {len(entities_with_leaks)}")

if entities_with_leaks:
    print("\nDetalle de fugas:")
    for item in entities_with_leaks[:10]:
        print(f"\n  Entity {item['entity_id']} (pseudónimo: {item['pseudonym']}):")
        for leak in item['leaks'][:5]:
            print(f"    - Original '{leak['original']}' en registro {leak['record_id']}")
