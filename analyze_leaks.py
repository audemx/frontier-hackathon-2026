#!/usr/bin/env python3
"""Script para analizar fugas de PII en los archivos de salida."""

import json
import re
from pathlib import Path

def strip_accents(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )

def norm_text(s: str) -> str:
    return strip_accents(s).lower()

def solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)

# Cargar entities.json
entities_path = Path("output/entities.json")
with open(entities_path) as f:
    entities_data = json.load(f)

# Crear índice de originales
originals_index = {}
for entity in entities_data["entities"]:
    eid = entity["entity_id"]
    for orig in entity.get("originals", []):
        if len(orig) >= 3:
            originals_index[orig] = eid
            originals_index[orig.lower()] = eid
            originals_index[strip_accents(orig).lower()] = eid

print(f"Total de entidades: {len(entities_data['entities'])}")
print(f"Total de originales indexados: {len(originals_index)}")

# Verificar específicamente p_003
p003 = [e for e in entities_data["entities"] if e["entity_id"] == "p_003"][0]
print(f"\nEntidad p_003:")
print(f"  Originales: {p003['originals']}")
print(f"  Pseudónimos: {p003.get('pseudonyms', {})}")
print(f"  Records: {len(p003.get('records', []))}")

# Buscar fugas en archivos de salida
leaks = []

# Verificar chats.jsonl
chats_path = Path("output/chats.jsonl")
with open(chats_path) as f:
    for line_num, line in enumerate(f, 1):
        rec = json.loads(line)
        record_id = rec.get("id", "")
        
        # Serializar contenido del registro
        content_parts = []
        content_parts.append(rec.get("author", ""))
        content_parts.append(rec.get("text", ""))
        for att in rec.get("attachments", []):
            content_parts.append(att.get("filename", ""))
        
        full_content = " | ".join(content_parts)
        
        # Buscar originales de p_003
        for orig in p003["originals"]:
            # Búsqueda exacta
            if orig in full_content:
                leaks.append({
                    "file": "chats.jsonl",
                    "line": line_num,
                    "record_id": record_id,
                    "entity": "p_003",
                    "original": orig,
                    "location": "exact match"
                })
            # Búsqueda normalizada
            elif norm_text(orig) in norm_text(full_content):
                leaks.append({
                    "file": "chats.jsonl",
                    "line": line_num,
                    "record_id": record_id,
                    "entity": "p_003",
                    "original": orig,
                    "location": "normalized match"
                })
            # Búsqueda de dígitos
            orig_digits = solo_digitos(orig)
            if orig_digits and len(orig_digits) >= 6:
                content_digits = solo_digitos(full_content)
                if orig_digits in content_digits:
                    leaks.append({
                        "file": "chats.jsonl",
                        "line": line_num,
                        "record_id": record_id,
                        "entity": "p_003",
                        "original": orig,
                        "location": f"digits match: {orig_digits}"
                    })

print(f"\nFugas encontradas: {len(leaks)}")
for leak in leaks[:20]:
    print(f"  {leak}")
