"""LLM Agent and Contextual Processing Module.

Handles quasi-identifier generalization (occupation + neighborhood + year),
contextual entity extraction, and homonym disambiguation.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from src.config import DEFAULT_MODEL, OPENROUTER_API_KEY, query_llm

logger = logging.getLogger("agent")

# Predefined dictionary for Colombian occupations to generalized sectors
OCCUPATION_MAP: Dict[str, str] = {
    "fotógrafa": "profesional de las industrias creativas",
    "fotógrafo": "profesional de las industrias creativas",
    "diseñador gráfico": "profesional de las industrias creativas",
    "diseñadora gráfica": "profesional de las industrias creativas",
    "community manager": "profesional de medios",
    "periodista": "profesional de medios",
    "administrador": "profesional de servicios",
    "administradora": "profesional de servicios",
    "comerciante": "profesional de servicios",
    "estilista": "profesional de servicios",
    "mecánico": "profesional del transporte",
    "conductor de plataforma": "profesional del transporte",
    "piloto comercial": "profesional del transporte",
    "electricista": "profesional técnico",
    "panadero": "profesional técnico",
    "contador": "profesional contable",
    "contadora": "profesional contable",
    "auxiliar contable": "profesional contable",
    "abogado": "profesional legal",
    "abogada": "profesional legal",
    "estudiante de derecho": "profesional legal",
    "enfermera": "profesional de la salud",
    "odontóloga": "profesional de la salud",
    "fisioterapeuta": "profesional de la salud",
    "psicóloga": "profesional de la salud",
    "estudiante de medicina": "profesional de la salud",
    "veterinaria": "profesional de la salud animal",
    "veterinario": "profesional de la salud animal",
    "ingeniera de sistemas": "profesional de tecnología",
    "ingeniero de sistemas": "profesional de tecnología",
    "ingeniero civil": "profesional de ingeniería",
    "arquitecta": "profesional de arquitectura",
    "arquitecto": "profesional de arquitectura",
    "docente": "profesional de la educación",
    "chef": "profesional gastronómico",
}

# Predefined mapping of Colombian neighborhoods to their respective cities
BARRIO_TO_CITY: Dict[str, str] = {
    "Granada": "Cali",
    "El Peñón": "Cali",
    "Santa Mónica": "Cali",
    "San Antonio": "Cali",
    "Ciudad Jardín": "Cali",
    "Itagüí": "Medellín",
    "Envigado": "Medellín",
    "Belén": "Medellín",
    "Castilla": "Medellín",
    "Poblado": "Medellín",
    "El Poblado": "Medellín",
    "Laureles": "Medellín",
    "Boston": "Medellín",
    "Buenos Aires": "Medellín",
    "Robledo": "Medellín",
    "Cabecera": "Bucaramanga",
    "Cañaveral": "Bucaramanga",
    "Sotomayor": "Bucaramanga",
    "Real de Minas": "Bucaramanga",
    "Chapinero": "Bogotá",
    "Cedritos": "Bogotá",
    "Chicó": "Bogotá",
    "El Chicó": "Bogotá",
    "Usaquén": "Bogotá",
    "Suba": "Bogotá",
    "Teusaquillo": "Bogotá",
    "Bocagrande": "Cartagena",
    "Castillogrande": "Cartagena",
    "Crespo": "Cartagena",
    "Manga": "Cartagena",
    "Alto Prado": "Barranquilla",
    "El Prado": "Barranquilla",
    "Riomar": "Barranquilla",
    "Circunvalar": "Pereira",
    "Cuba": "Pereira",
}


def generalize_occupation(occupation: str) -> str:
    """Generalizes a specific occupation into a broad sector."""
    if not occupation:
        return occupation
    occ_clean = occupation.strip().lower()
    if occ_clean in OCCUPATION_MAP:
        return OCCUPATION_MAP[occ_clean]
    for key, val in OCCUPATION_MAP.items():
        if key in occ_clean:
            return val
    return occupation


def generalize_barrio(barrio: str) -> str:
    """Generalizes a neighborhood to its metropolitan city or broad area."""
    if not barrio:
        return barrio
    barrio_clean = barrio.strip()
    for b_name, city in BARRIO_TO_CITY.items():
        if re.search(rf"\b{re.escape(b_name)}\b", barrio_clean, re.IGNORECASE):
            return city
    return barrio


def generalize_quasi_identifiers(text: str) -> str:
    """Detects and breaks quasi-identifier triples (barrio + occupation + year) in text.

    Generalizes occupation to broad sector, barrio to city, and year to 'hace unos años'.
    """
    if not text:
        return text

    result = text

    # Check for presence of any known occupation
    found_occ = None
    for occ, sector in OCCUPATION_MAP.items():
        pattern = rf"\b{re.escape(occ)}\b"
        if re.search(pattern, result, re.IGNORECASE):
            found_occ = (pattern, sector)
            break

    # Check for presence of any known barrio
    found_barrio = None
    for barrio, city in BARRIO_TO_CITY.items():
        pattern = rf"\b{re.escape(barrio)}\b"
        if re.search(pattern, result, re.IGNORECASE):
            found_barrio = (pattern, city)
            break

    # Check for presence of recent years (2018-2026)
    year_pattern = r"\b(201[89]|202[0-6])\b"
    has_year = bool(re.search(year_pattern, result))

    # If at least 2 components co-occur, generalize to break linkage
    co_occurrences = sum([bool(found_occ), bool(found_barrio), has_year])
    if co_occurrences >= 2:
        if found_occ:
            result = re.sub(found_occ[0], found_occ[1], result, flags=re.IGNORECASE)
        if found_barrio:
            result = re.sub(found_barrio[0], found_barrio[1], result, flags=re.IGNORECASE)
        if has_year:
            # Replace year with "hace unos años"
            result = re.sub(year_pattern, "hace unos años", result)

    return result


def extract_entities_with_llm(text: str) -> List[Dict[str, Any]]:
    """Uses LLM via OpenRouter to extract entities from an unstructured text."""
    if not OPENROUTER_API_KEY or not text or len(text.strip()) < 5:
        return []

    prompt = f"""Analiza el siguiente texto de un sistema financiero y extrae entidades personales:
- Nombres propios de personas (clientes, agentes, familiares)
- Correos electrónicos (incluso si están deletreados como 'usuario arroba dominio punto com')
- Números de identificación / cédulas
- Teléfonos
- Direcciones

Texto:
\"\"\"{text}\"\"\"

Responde ÚNICAMENTE con un JSON válido con la siguiente estructura:
{{
  "entities": [
    {{
      "type": "person",
      "text": "forma exacta encontrada en el texto",
      "category": "name|email|cedula|phone|address"
    }}
  ]
}}
Si no hay entidades personales, responde con {{"entities": []}}.
"""
    try:
        raw_response = query_llm(
            prompt=prompt,
            system_prompt="Eres un extractor preciso de entidades PII. Devuelve solo JSON válido sin markdown adicional.",
            model=DEFAULT_MODEL,
            temperature=0.0,
            max_tokens=500,
        )
        clean_json = raw_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()

        data = json.loads(clean_json)
        return data.get("entities", [])
    except Exception as exc:
        logger.warning(f"LLM entity extraction failed: {exc}")
        return []


def disambiguate_homonym(
    name: str,
    context: str,
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Chooses the correct entity among multiple individuals sharing the same name.

    First matches deterministic cues (city, document number, email domain, phone, client_id).
    Falls back to LLM if ambiguity persists.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    context_lower = context.lower()

    # Rule 1: Direct match on client_id or document number or email
    for cand in candidates:
        client_id = cand.get("cliente_id", "").lower()
        if client_id and client_id in context_lower:
            return cand
        num_doc = str(cand.get("num_doc", "")).lower()
        if num_doc and num_doc in context_lower:
            return cand
        email = cand.get("email", "").lower()
        if email and email in context_lower:
            return cand

    # Rule 2: City / Barrio matching
    for cand in candidates:
        ciudad = cand.get("ciudad", "").lower()
        if ciudad and ciudad in context_lower:
            return cand
        barrio = cand.get("barrio", "").lower()
        if barrio and barrio in context_lower:
            return cand

    # Rule 3: LLM Disambiguation if API key is configured
    if OPENROUTER_API_KEY:
        try:
            cand_summaries = [
                f"Opción {i}: ID={c.get('cliente_id')}, Cédula={c.get('num_doc')}, Ciudad={c.get('ciudad')}, Ocupación={c.get('ocupacion')}"
                for i, c in enumerate(candidates)
            ]
            prompt = f"""En el siguiente contexto se menciona el nombre '{name}':
Contexto: "{context}"

Candidatos posibles:
{chr(10).join(cand_summaries)}

¿Cuál de las opciones corresponde al contexto? Responde ÚNICAMENTE con el número de índice (ej: 0 o 1).
"""
            ans = query_llm(prompt=prompt, temperature=0.0, max_tokens=10).strip()
            match = re.search(r"\b(\d+)\b", ans)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < len(candidates):
                    return candidates[idx]
        except Exception as exc:
            logger.warning(f"LLM disambiguation failed: {exc}")

    # Default fallback: return the first candidate
    return candidates[0]

