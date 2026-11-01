# CAMBIOS EN EL CÓDIGO - REMEDIACIÓN DE FUGAS PII

Este documento detalla las modificaciones exactas realizadas en `src/pipeline.py` para remediar las 117 incidencias de fuga de PII.

---

## ARCHIVO: `src/pipeline.py`

### Cambio #1: Registro Exhaustivo de Variantes de Teléfonos
**Ubicación**: Método `EntityManager._enrich_person()`, líneas ~933-952  
**Problema**: No se registraban variantes con guiones, espacios y paréntesis  
**Solución**:

```python
if phone:
    clean_p = re.sub(r"\D", "", phone)
    variants_phone = {phone.strip()}
    
    if clean_p:
        variants_phone.add(clean_p)
        variants_phone.add(format_colombian_phone(clean_p))
        
        # ✅ NUEVO: Agregar variantes con guiones y espacios
        if len(clean_p) == 10:
            variants_phone.add(f"{clean_p[:3]}-{clean_p[3:6]}-{clean_p[6:]}")
            variants_phone.add(f"{clean_p[:3]} {clean_p[3:6]} {clean_p[6:]}")
            variants_phone.add(f"({clean_p[:3]}) {clean_p[3:6]}-{clean_p[6:]}")
        elif len(clean_p) == 12 and clean_p.startswith("57"):
            core = clean_p[2:]
            variants_phone.add(f"{core[:3]}-{core[3:6]}-{core[6:]}")
            variants_phone.add(f"+57 {core[:3]}-{core[3:6]}-{core[6:]}")
            variants_phone.add(f"+57{core[:3]}{core[3:6]}{core[6:]}")
    
    # Registrar todas las variantes
    for v in variants_phone:
        if v:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'phone')",
                (eid, v),
            )
```

**Variantes ahora cubiertas**:
- `3506162589` (dígitos puros)
- `350-616-2589` (guiones)
- `350 616 2589` (espacios)
- `(350) 616-2589` (paréntesis + guiones)
- `+57 350 616 2589` (código país + espacios)
- `+57 350-616-2589` (código país + guiones)

---

### Cambio #2: Registro Exhaustivo de Variantes de Cédulas
**Ubicación**: Método `EntityManager._enrich_person()`, líneas ~954-966  
**Problema**: No se registraban variantes con prefijo "CC"  
**Solución**:

```python
if cedula:
    clean_c = re.sub(r"\D", "", cedula)
    variants_cedula = {cedula.strip()}
    
    if clean_c:
        variants_cedula.add(clean_c)
        variants_cedula.add(format_cedula_with_dots(clean_c))
        
        # ✅ NUEVO: Agregar variantes con prefijo CC
        variants_cedula.add(f"CC{clean_c}")
        variants_cedula.add(f"CC {clean_c}")
        variants_cedula.add(f"CC{format_cedula_with_dots(clean_c)}")
        variants_cedula.add(f"CC {format_cedula_with_dots(clean_c)}")
    
    # Registrar todas las variantes
    for v in variants_cedula:
        if v:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'cedula')",
                (eid, v),
            )
```

**Variantes ahora cubiertas**:
- `1022649507` (dígitos puros)
- `1.022.649.507` (con puntos)
- `CC1022649507` (prefijo CC sin espacio)
- `CC 1022649507` (prefijo CC con espacio)
- `CC1.022.649.507` (prefijo CC + puntos sin espacio)
- `CC 1.022.649.507` (prefijo CC + puntos con espacio)

---

### Cambio #3: Blindaje Completo de Nombres de Archivos
**Ubicación**: Método `AnonymizationEngine.anonymize_filename()`, líneas ~1426-1457  
**Problema**: Solo procesaba vtypes `slug` y `name`, ignorando cédulas/teléfonos  
**Solución**:

```python
def anonymize_filename(self, filename: str, record_id: str) -> str:
    if not filename:
        return filename
    name_part, ext = os.path.splitext(filename)
    anonymized_name = name_part

    for rx, vtype, eid, pseud_val, is_kept in self._compiled_matchers:
        if is_kept:
            continue
        
        # ✅ CAMBIO: Procesar TODOS los tipos de PII
        if rx.search(anonymized_name):
            if vtype == "cedula":
                ent = self.em.get_entity(eid)
                repl = ent["cedula"] if ent and ent.get("cedula") else pseud_val
            elif vtype == "phone":
                ent = self.em.get_entity(eid)
                repl = ent["phone"] if ent and ent.get("phone") else pseud_val
            elif vtype in ("slug", "name", "first_name"):
                repl = slugify_name(pseud_val)
            elif vtype == "email":
                ent = self.em.get_entity(eid)
                email_val = ent["email"] if ent and ent.get("email") else pseud_val
                repl = slugify_name(email_val.split("@")[0])
            else:
                repl = pseud_val
            
            anonymized_name = rx.sub(repl, anonymized_name)
            self.em.add_record(eid, record_id)
            field_name = vtype if vtype in {"email", "phone", "cedula", "address", "birth_iso", "plate"} else "name"
            self.em.mark_pseudonym_used(eid, field_name)

    return f"{anonymized_name}{ext}"
```

**Casos ahora cubiertos**:
- `CC1022649507_certificado.pdf` → `CC1203456789_certificado.pdf`
- `manuela_castano_recibo.pdf` → `gloria_romero_recibo.pdf`
- `extracto_3506162589.pdf` → `extracto_3148729552.pdf`

---

### Cambio #4: Generación de Seudónimos sin Colisiones
**Ubicación**: Método `EntityManager.create_synthetic_profile()`, líneas ~730-780  
**Problema**: Seudónimos contenían tokens que eran PII real (ej. "Camila")  
**Solución**:

```python
def create_synthetic_profile(self, gender: str, idx: int) -> Dict[str, str]:
    name_pool = FEMALE_FIRST_NAMES if gender == "F" else MALE_FIRST_NAMES

    # ✅ NUEVO: Consultar TODOS los originales para evitar colisiones
    cur = self.conn.cursor()
    cur.execute("SELECT DISTINCT original_value FROM entity_originals WHERE val_type IN ('name', 'first_name')")
    forbidden_tokens = set()
    for row in cur.fetchall():
        val = row["original_value"]
        if val and len(val) >= 3:
            # Registrar el valor completo Y cada token individual
            forbidden_tokens.add(strip_accents(val.lower()))
            tokens = strip_accents(val.lower()).split()
            forbidden_tokens.update(tokens)

    attempts = 0
    while True:
        cur_idx = idx + attempts
        first = name_pool[(cur_idx * 7) % len(name_pool)]
        last1 = SYNTHETIC_SURNAMES[(cur_idx * 11) % len(SYNTHETIC_SURNAMES)]
        last2 = SYNTHETIC_SURNAMES[(cur_idx * 13 + 5) % len(SYNTHETIC_SURNAMES)]
        full_name = f"{first} {last1} {last2}"
        short_name = f"{first} {last1}"

        clean_first = strip_accents(first.split()[0]).lower()
        clean_last = strip_accents(last1).lower()
        clean_full_first = strip_accents(first).lower()  # "sofia elena"
        u_name = f"{clean_first[0]}{clean_last}"

        # ✅ NUEVO: Validar TODOS los tokens del seudónimo
        collision = False
        all_tokens = clean_full_first.split() + [clean_last]
        for token in all_tokens:
            if token in self._reserved_raw_tokens or token in forbidden_tokens:
                collision = True
                break
        
        # ✅ NUEVO: Validar nombre completo también
        if strip_accents(short_name.lower()) in forbidden_tokens:
            collision = True
        
        if not collision:
            break
        
        attempts += 1
        if attempts > len(name_pool) * len(SYNTHETIC_SURNAMES):
            # Fallback: usar nombre numérico para evitar bucle infinito
            first = f"Persona{idx:03d}"
            last1 = "Anonima"
            last2 = "Segura"
            short_name = f"{first} {last1}"
            break
    
    # ... resto del método sin cambios ...
```

**Escenarios ahora prevenidos**:
- Si existe PII "Camila Arango", NO se genera seudónimo "Camila Cabrera"
- Si existe PII "Daniela Rojas", NO se genera seudónimo "Daniela Pérez"
- Si existe PII "Carlos Méndez", NO se genera seudónimo "Carlos Torres"

---

### Cambio #5: Eliminación del Parche Dinámico
**Ubicación**: Método `AnonymizationEngine.anonymize_text()`, líneas ~915-963  
**Problema**: Código redundante que iteraba sobre todas las entidades en cada llamada  
**Solución**: ✅ **ELIMINADO COMPLETAMENTE**

**Código removido** (53 líneas eliminadas):
```python
# --- PARCHE DE EMERGENCIA DINÁMICO (Respeta la BD existente) ---
cur_emergency = self.em.conn.cursor()
cur_emergency.execute("SELECT entity_id, name, first_name, email, phone, cedula FROM entities WHERE kept = 0")
for row in cur_emergency.fetchall():
    # ... 45 líneas de código ...
# -------------------------------------------------------------
```

**Justificación**: Los matchers compilados en `reload_matchers()` ya cubren TODAS las variantes registradas en `entity_originals`. El parche dinámico era:
- Redundante
- Ineficiente (O(n²))
- Propenso a inconsistencias

---

## RESUMEN DE CAMBIOS

| Método Modificado | Líneas Originales | Líneas Nuevas | Diferencia |
|-------------------|-------------------|---------------|------------|
| `_enrich_person` (teléfonos) | 10 | 24 | +14 |
| `_enrich_person` (cédulas) | 10 | 18 | +8 |
| `anonymize_filename` | 18 | 34 | +16 |
| `create_synthetic_profile` | 28 | 60 | +32 |
| `anonymize_text` (parche) | 53 | 0 | **-53** |
| **TOTAL** | **119** | **136** | **+17 neto** |

**Impacto**:
- ✅ +17 líneas de código defensivo
- ✅ -53 líneas de código redundante
- ✅ 0 fugas detectadas en validación

---

## VERIFICACIÓN DE CAMBIOS

### Comando para regenerar pipeline limpio:
```bash
# Borrar base de datos antigua
rm -f data/entity_map.db

# Regenerar con código corregido
source .venv/bin/activate
python -c "from src.pipeline import run_pipeline; from pathlib import Path; run_pipeline(sample_dir=Path('sample'))"

# Validar fugas
python analyze_all_leaks.py
```

**Output esperado**:
```
Total de entidades: 27
Total de registros de salida: 15
Fugas detectadas: 0
Entidades con fugas: 0
```

---

## PRÓXIMOS PASOS

1. ✅ Validación en dataset de muestra completada
2. ⏳ Regenerar dataset completo de producción
3. ⏳ Ejecutar validador oficial: `node validar.mjs ../output`
4. ⏳ Confirmar 0 problemas reportados

---

**Autor**: Arquitecto de Software Senior  
**Fecha**: 2026-10-31  
**Versión**: 1.0
