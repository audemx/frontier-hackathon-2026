"""Core Anonymization Pipeline Module.

Implements the 3-layer anonymization engine:
Layer 1: Regex Anti-Evasion (spelled-out emails, cédulas, phones, plates, Slack mentions)
Layer 2: Contextual Entity Extraction, Homonym Disambiguation, and Quasi-Identifier Generalization
Layer 3: Deterministic SQLite Persistence (data/entity_map.db) and Verification Guardrail matching validar.mjs
"""

import csv
import io
import json
import logging
import os
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import requests
from pypdf import PdfReader
from bs4 import BeautifulSoup

from src.agent import (
    disambiguate_homonym,
    generalize_barrio,
    generalize_occupation,
    generalize_quasi_identifiers,
)
from src.config import DB_PATH, OUTPUT_DIR, SAMPLE_DIR

logger = logging.getLogger("pipeline")
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# Text Normalization & Containment Helper (mirrors validar.mjs exactly)
# -----------------------------------------------------------------------------
CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "А": "A", "Е": "E", "О": "O", "Р": "P",
    "С": "C", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S", "В": "B",
    "Н": "H", "К": "K", "М": "M", "Т": "T", "ο": "o", "α": "a", "ρ": "p",
    "ν": "v", "ι": "i", "ℓ": "l", "ı": "i", "ɑ": "a"
}


def clean_text(s: str) -> str:
    base = unicodedata.normalize("NFKC", s)
    res = "".join(CONFUSABLES.get(c, c) for c in base)
    res = re.sub(r"[\t\r\n\v\f\s]+", " ", res)
    return res


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", clean_text(s)) if unicodedata.category(c) != "Mn"
    )


def norm_text(s: str) -> str:
    return strip_accents(s).lower()


def solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


def digitos_en(haystack: str, digitos: str) -> bool:
    compact = re.sub(r"\D", "", haystack)
    candidatos = {digitos}
    if len(digitos) == 12 and digitos.startswith("57"):
        candidatos.add(digitos[2:])
    for d in candidatos:
        if d and re.search(rf"(?<!\d)(?:57)?{re.escape(d)}(?!\d)", compact):
            return True
    return False


def contiene(haystack: str, needle: str) -> bool:
    """Evaluates text containment identically to validar.mjs."""
    if not needle or not haystack:
        return False
    digitos = solo_digitos(needle)
    if digitos and len(digitos) >= 6 and len(digitos) >= 0.6 * len(needle) and not re.search(r"[a-zA-Z]", needle):
        return digitos_en(haystack, digitos)

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


def plano(val: Any) -> List[str]:
    """Flattens structured objects into a list of strings identically to validar.mjs."""
    if val is None:
        return []
    if isinstance(val, (str, int, float, bool)):
        return [str(val)]
    if isinstance(val, list):
        res = []
        for item in val:
            res.extend(plano(item))
        return res
    if isinstance(val, dict):
        res = []
        for k, v in val.items():
            res.append(str(k))
            res.extend(plano(v))
        return res
    return [str(val)]


def record_text_content(rec: Dict[str, Any]) -> str:
    """Serializes a record excluding 'id' for containment checks."""
    sin_id = {k: v for k, v in rec.items() if k != "id"}
    return " | ".join(plano(sin_id))


# -----------------------------------------------------------------------------
# Synthetic Data Pool for Colombian Profiles
# -----------------------------------------------------------------------------
MALE_FIRST_NAMES = [
    "Carlos Andrés", "Juan David", "Diego Fernando", "Mateo", "Santiago",
    "Felipe", "Alejandro", "Andrés Felipe", "Daniel", "Sebastián",
    "Esteban", "Nicolás", "Gabriel", "Julián", "Mauricio",
    "Leonardo", "Fernando", "Ricardo", "Hugo", "Javier",
    "Óscar", "Rodrigo", "Tomás", "Guillermo", "Rafael",
    "Pedro", "Pablo", "Alberto", "Gonzalo", "Hernán",
]

FEMALE_FIRST_NAMES = [
    "Sofía Elena", "Valentina", "Mariana", "Camila", "Isabella",
    "Daniela", "Gabriela", "Lucía", "Catalina", "Carolina",
    "Natalia", "Elena", "Laura Marcela", "Paula Andrea", "Liliana",
    "Diana Marcela", "Amalia", "Doris", "Norma", "Marcela",
    "Adriana", "Gloria", "Tatiana", "Valeria", "Verónica",
    "Victoria", "Ximena", "Beatriz", "Clara", "Sandra",
]

SYNTHETIC_SURNAMES = [
    "Zambrano", "Pardo", "Lozano", "Naranjo", "Pineda",
    "Cano", "Valencia", "Mejía", "Hoyos", "Ospina",
    "Gómez", "Rodríguez", "Martínez", "Hernández", "López",
    "González", "Pérez", "Sánchez", "Ramírez", "Torres",
    "Flores", "Rivera", "Díaz", "Reyes", "Morales",
    "Ortiz", "Gutiérrez", "Castro", "Chávez", "Mendoza",
    "Silva", "Vargas", "Suárez", "Romero", "Herrera",
    "Medina", "Aguilar", "Vega", "Peña", "Cabrera",
]

DOMAINS = ["gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "icloud.com"]

KEPT_ORGANIZATIONS = [
    ("Bancolombia", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Superfinanciera", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Nequi", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Daviplata", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Davivienda", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Banco de Bogotá", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Banco de Occidente", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Santander", "organización, lugar, marca o figura pública; no es persona natural"),
    ("BBVA", "organización, lugar, marca o figura pública; no es persona natural"),
    ("PSE", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Rappi", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Nutresa", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Andes Capital", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Carulla", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Éxito", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Plaza Botero", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Shakira", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Transmilenio", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Metro de Medellín", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Kipu Pay", "organización, lugar, marca o figura pública; no es persona natural"),
    ("Kipu", "organización, lugar, marca o figura pública; no es persona natural"),
]


def slugify_name(name: str) -> str:
    s = strip_accents(name).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def format_cedula_with_dots(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    if not digits:
        return num
    parts = []
    while digits:
        parts.insert(0, digits[-3:])
        digits = digits[:-3]
    return ".".join(parts)


def format_colombian_phone(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    if len(digits) == 12 and digits.startswith("57"):
        digits = digits[2:]
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return num


# -----------------------------------------------------------------------------
# Layer 3: SQLite Persistent Entity Database
# -----------------------------------------------------------------------------
class EntityManager:
    """Manages persistent deterministic mapping of real entities to synthetic profiles."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self._seed_kept_entities()
        self._person_counter = self._get_next_person_id_num()
        self._reserved_raw_tokens: Set[str] = set()

    def _init_db(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    gender TEXT,
                    name TEXT,
                    first_name TEXT,
                    email TEXT,
                    phone TEXT,
                    cedula TEXT,
                    address TEXT,
                    birth_iso TEXT,
                    plate TEXT,
                    passport TEXT,
                    account TEXT,
                    handle TEXT,
                    kept INTEGER DEFAULT 0,
                    reason TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_originals (
                    entity_id TEXT NOT NULL,
                    original_value TEXT NOT NULL,
                    val_type TEXT NOT NULL,
                    PRIMARY KEY (entity_id, original_value)
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orig_val ON entity_originals(original_value)"
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_records (
                    entity_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    PRIMARY KEY (entity_id, record_id)
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rec_id ON entity_records(record_id)"
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS used_pseudonym_fields (
                    entity_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    PRIMARY KEY (entity_id, field_name)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    chats_count INTEGER DEFAULT 0,
                    docs_count INTEGER DEFAULT 0,
                    tables_count INTEGER DEFAULT 0,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    seconds REAL DEFAULT 0,
                    error TEXT
                )
                """
            )

    def _seed_kept_entities(self):
        with self.conn:
            for idx, (org, reason) in enumerate(KEPT_ORGANIZATIONS, start=1):
                eid = f"kept_{idx:03d}"
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO entities (entity_id, type, kept, reason)
                    VALUES (?, 'organization_or_place', 1, ?)
                    """,
                    (eid, reason),
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_originals (entity_id, original_value, val_type)
                    VALUES (?, ?, 'organization')
                    """,
                    (eid, org),
                )

    def _get_next_person_id_num(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT entity_id FROM entities WHERE entity_id LIKE 'p_%'")
        rows = cur.fetchall()
        max_num = 0
        for r in rows:
            try:
                num = int(r["entity_id"].split("_")[1])
                if num > max_num:
                    max_num = num
            except (IndexError, ValueError):
                pass
        return max_num + 1

    def add_reserved_raw_tokens(self, tokens: List[str]):
        for t in tokens:
            if t:
                self._reserved_raw_tokens.add(t.strip().lower())
                self._reserved_raw_tokens.add(strip_accents(t.strip().lower()))

    def detect_gender(self, name: str) -> str:
        first_token = name.strip().split()[0].lower() if name.strip() else ""
        first_token_no_accent = strip_accents(first_token)

        female_specific = {
            "yesenia", "kelly", "nohora", "manuela", "amalia", "doris",
            "marcela", "liliana", "camila", "alejandra", "pamela", "fernanda",
            "clara", "bibiana", "emilia", "adela", "celeste", "daniela", "carolina",
            "rosa", "norma", "ana", "dora", "lucia", "maria", "paola"
        }
        male_specific = {
            "david", "farid", "luis", "esteban", "hugo", "carlos", "benjamin",
            "brayan", "milton", "adrian", "nicolas", "julian", "martin", "juan",
            "diego", "andres", "felipe", "mateo", "santiago", "dagoberto", "norberto"
        }

        if first_token_no_accent in female_specific:
            return "F"
        if first_token_no_accent in male_specific:
            return "M"
        if first_token_no_accent.endswith("a") or first_token_no_accent.endswith("is"):
            return "F"
        return "M"

    def create_synthetic_profile(self, gender: str, idx: int) -> Dict[str, str]:
        name_pool = FEMALE_FIRST_NAMES if gender == "F" else MALE_FIRST_NAMES

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
            u_name = f"{clean_first[0]}{clean_last}"

            # Ensure collision-free against input tokens
            if (
                u_name not in self._reserved_raw_tokens
                and clean_last not in self._reserved_raw_tokens
                and short_name.lower() not in self._reserved_raw_tokens
            ):
                break
            attempts += 1

        domain = DOMAINS[(idx * 3) % len(DOMAINS)]
        email = f"{u_name}@{domain}"

        phone_mid = (idx * 37 + 100) % 900 + 100
        phone_end = (idx * 53 + 1000) % 9000 + 1000
        phone = f"31{idx % 3 + 0}{phone_mid}{phone_end}"[:10]

        cedula_num = 1000000000 + (idx * 1374921) % 900000000
        cedula = str(cedula_num)

        street_num = (idx * 17) % 180 + 1
        addr_num1 = (idx * 23) % 120 + 1
        addr_num2 = (idx * 29) % 90 + 1
        address = f"Diagonal {street_num} # {addr_num1}-{addr_num2}"

        year = 1970 + (idx * 3) % 35
        month = (idx * 5) % 12 + 1
        day = (idx * 7) % 28 + 1
        birth_iso = f"{year:04d}-{month:02d}-{day:02d}"

        letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
        l1 = letters[(idx * 3) % len(letters)]
        l2 = letters[(idx * 5) % len(letters)]
        l3 = letters[(idx * 7) % len(letters)]
        p_num = (idx * 19) % 900 + 100
        plate = f"{l1}{l2}{l3}{p_num}"

        return {
            "name": short_name,
            "first_name": first,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "cedula": cedula,
            "address": address,
            "birth_iso": birth_iso,
            "plate": plate,
        }

    def register_person(
        self,
        name: str,
        gender: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        cedula: Optional[str] = None,
        address: Optional[str] = None,
        birth_iso: Optional[str] = None,
        plate: Optional[str] = None,
        corporate: bool = False,
    ) -> str:
        for val, vtype in [(cedula, "cedula"), (email, "email"), (phone, "phone")]:
            if val:
                existing = self.find_entity_by_original(val)
                if existing:
                    self._enrich_person(existing["entity_id"], name, email, phone, cedula, address, birth_iso, plate)
                    return existing["entity_id"]

        if name and not cedula and not email and not phone:
            existing = self.find_entity_by_original(name)
            if existing:
                self._enrich_person(existing["entity_id"], name, email, phone, cedula, address, birth_iso, plate)
                return existing["entity_id"]

        g = gender or self.detect_gender(name)
        idx = self._person_counter
        self._person_counter += 1
        eid = f"p_{idx:03d}"

        synth = self.create_synthetic_profile(g, idx)
        if corporate:
            clean_first = strip_accents(synth["name"].split()[0]).lower()
            clean_last = strip_accents(synth["name"].split()[1]).lower()
            synth["email"] = f"{clean_first}.{clean_last}@kipupay.co"

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO entities (
                    entity_id, type, gender, name, first_name, email, phone, cedula,
                    address, birth_iso, plate, kept
                ) VALUES (?, 'person', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    eid, g, synth["name"], synth.get("first_name", synth["name"].split()[0]),
                    synth["email"], synth["phone"], synth["cedula"], synth["address"],
                    synth["birth_iso"], synth["plate"]
                ),
            )

        self._enrich_person(eid, name, email, phone, cedula, address, birth_iso, plate)
        return eid

    def _enrich_person(
        self,
        eid: str,
        name: Optional[str],
        email: Optional[str],
        phone: Optional[str],
        cedula: Optional[str],
        address: Optional[str],
        birth_iso: Optional[str],
        plate: Optional[str],
    ):
        with self.conn:
            if name:
                cleaned_name = name.strip()
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'name')",
                    (eid, cleaned_name),
                )
                parts = cleaned_name.split()
                if len(parts) >= 2:
                    short_name = f"{parts[0]} {parts[1]}"
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'name')",
                        (eid, short_name),
                    )
                    first_token = parts[0]
                    if len(first_token) >= 4 and first_token.lower() not in {"maria", "juan", "jose", "luis", "dona", "senor"}:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'first_name')",
                            (eid, first_token),
                        )
                elif len(parts) == 1 and len(parts[0]) >= 4:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'first_name')",
                        (eid, parts[0]),
                    )

                slug = slugify_name(name)
                if len(slug) >= 4:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'slug')",
                        (eid, slug),
                    )
                if len(parts) >= 2:
                    short_slug = slugify_name(f"{parts[0]} {parts[1]}")
                    if len(short_slug) >= 4:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'slug')",
                            (eid, short_slug),
                        )
            if email:
                clean_email = email.strip()
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'email')",
                    (eid, clean_email),
                )
                u_part = clean_email.split("@")[0]
                if len(u_part) >= 3:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'username')",
                        (eid, u_part),
                    )
            if phone:
                clean_p = re.sub(r"\D", "", phone)
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'phone')",
                    (eid, phone.strip()),
                )
                if clean_p:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'phone')",
                        (eid, clean_p),
                    )
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'phone')",
                        (eid, format_colombian_phone(clean_p)),
                    )
            if cedula:
                clean_c = re.sub(r"\D", "", cedula)
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'cedula')",
                    (eid, cedula.strip()),
                )
                if clean_c:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'cedula')",
                        (eid, clean_c),
                    )
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'cedula')",
                        (eid, format_cedula_with_dots(clean_c)),
                    )
            if address:
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'address')",
                    (eid, address.strip()),
                )
            if birth_iso:
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'birth_iso')",
                    (eid, birth_iso.strip()),
                )
            if plate:
                clean_plate = re.sub(r"[^A-Za-z0-9]", "", plate).upper()
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'plate')",
                    (eid, plate.strip()),
                )
                if clean_plate:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'plate')",
                        (eid, clean_plate),
                    )

    def link_slack_user(self, uid: str, name: str, real_name: str, email: str, phone: str) -> str:
        eid = None
        if email:
            existing = self.find_entity_by_original(email)
            if existing:
                eid = existing["entity_id"]
        if not eid and phone:
            existing = self.find_entity_by_original(phone)
            if existing:
                eid = existing["entity_id"]
        if not eid and real_name:
            existing = self.find_entity_by_original(real_name)
            if existing:
                eid = existing["entity_id"]

        if not eid:
            is_corp = email.endswith("@kipupay.co") if email else False
            eid = self.register_person(
                name=real_name or name,
                email=email,
                phone=phone,
                corporate=is_corp,
            )

        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'uid')",
                (eid, uid),
            )
            if name:
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_originals VALUES (?, ?, 'username')",
                    (eid, name),
                )
        return eid

    def find_entity_by_original(self, val: str) -> Optional[Dict[str, Any]]:
        if not val:
            return None
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT e.* FROM entities e
            JOIN entity_originals o ON e.entity_id = o.entity_id
            WHERE o.original_value = ?
            LIMIT 1
            """,
            (val.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def add_record(self, entity_id: str, record_id: str):
        if not entity_id or not record_id:
            return
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_records (entity_id, record_id) VALUES (?, ?)",
                (entity_id, record_id),
            )

    def mark_pseudonym_used(self, entity_id: str, field: str):
        if not entity_id or not field:
            return
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO used_pseudonym_fields (entity_id, field_name) VALUES (?, ?)",
                (entity_id, field),
            )

    def get_all_originals_sorted(self) -> List[Tuple[str, str, str, str, bool]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT o.original_value, o.val_type, e.entity_id, e.kept,
                   e.name, e.first_name, e.email, e.phone, e.cedula, e.address, e.birth_iso, e.plate
            FROM entity_originals o
            JOIN entities e ON o.entity_id = e.entity_id
            ORDER BY LENGTH(o.original_value) DESC
            """
        )
        results = []
        for r in cur.fetchall():
            orig = r["original_value"]
            if len(orig) < 3:
                continue
            vtype = r["val_type"]
            eid = r["entity_id"]
            kept = bool(r["kept"])
            if kept:
                results.append((orig, vtype, eid, orig, True))
            else:
                pseud_val = r["name"]
                if vtype == "first_name":
                    pseud_val = r["first_name"] or r["name"].split()[0]
                elif vtype == "email" and r["email"]:
                    pseud_val = r["email"]
                elif vtype == "phone" and r["phone"]:
                    pseud_val = r["phone"]
                elif vtype == "cedula" and r["cedula"]:
                    pseud_val = r["cedula"]
                elif vtype == "address" and r["address"]:
                    pseud_val = r["address"]
                elif vtype == "birth_iso" and r["birth_iso"]:
                    pseud_val = r["birth_iso"]
                elif vtype == "plate" and r["plate"]:
                    pseud_val = r["plate"]
                elif vtype == "slug":
                    pseud_val = slugify_name(r["name"])
                elif vtype == "uid":
                    pseud_val = r["name"]
                elif vtype == "username":
                    pseud_val = slugify_name(r["name"]).replace("_", ".")
                results.append((orig, vtype, eid, pseud_val, False))
        return results

    def export_entities_json(self, all_output_records: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Constructs entities.json ensuring 100% adherence to validar.mjs."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM entities ORDER BY entity_id")
        ent_rows = cur.fetchall()

        entities_list = []
        for row in ent_rows:
            eid = row["entity_id"]
            is_kept = bool(row["kept"])
            etype = row["type"]

            # Originals
            cur.execute(
                "SELECT original_value FROM entity_originals WHERE entity_id = ? ORDER BY original_value",
                (eid,),
            )
            origs = [r["original_value"] for r in cur.fetchall()]

            if is_kept:
                entities_list.append({
                    "entity_id": eid,
                    "type": etype,
                    "originals": origs,
                    "pseudonyms": {},
                    "kept": True,
                    "reason": row["reason"] or "organización, lugar, marca o figura pública; no es persona natural",
                    "records": [],
                })
                continue

            # Fetch candidate records
            cur.execute(
                "SELECT record_id FROM entity_records WHERE entity_id = ? ORDER BY record_id",
                (eid,),
            )
            candidate_recs = [r["record_id"] for r in cur.fetchall()]

            # Audit against all output records: verify that pseudonym name actually appears
            pseud_name = row["name"]
            valid_recs = []
            if all_output_records:
                for rid in candidate_recs:
                    if rid in all_output_records:
                        rec_txt = record_text_content(all_output_records[rid])
                        if contiene(rec_txt, pseud_name):
                            valid_recs.append(rid)
            else:
                valid_recs = candidate_recs

            # If no valid records, do not export this unreferenced person!
            if not valid_recs:
                continue

            # Build pseudonyms dictionary containing ONLY fields that appear in valid_recs
            pseudonyms_obj: Dict[str, str] = {"name": pseud_name}

            if all_output_records:
                combined_recs_txt = " | ".join(
                    record_text_content(all_output_records[rid]) for rid in valid_recs if rid in all_output_records
                )
                for f in ["email", "phone", "cedula", "address", "birth_iso", "plate", "passport", "account"]:
                    val = row[f]
                    if val and contiene(combined_recs_txt, val):
                        pseudonyms_obj[f] = val
            else:
                cur.execute(
                    "SELECT field_name FROM used_pseudonym_fields WHERE entity_id = ?",
                    (eid,),
                )
                used_fields = {r["field_name"] for r in cur.fetchall()}
                for f in ["email", "phone", "cedula", "address", "birth_iso", "plate", "passport", "account"]:
                    val = row[f]
                    if val and f in used_fields:
                        pseudonyms_obj[f] = val

            entities_list.append({
                "entity_id": eid,
                "type": etype,
                "originals": origs,
                "pseudonyms": pseudonyms_obj,
                "records": sorted(list(set(valid_recs))),
            })

        return {"entities": entities_list}


# -----------------------------------------------------------------------------
# Layer 1 & 2: Regex Anti-Evasion & Contextual Text Anonymizer
# -----------------------------------------------------------------------------
class AnonymizationEngine:
    """Anonymizes free text and structured documents using the 3-layer architecture."""

    def __init__(self, entity_manager: EntityManager):
        self.em = entity_manager
        self._compiled_matchers: List[Tuple[re.Pattern, str, str, str, bool]] = []
        self.reload_matchers()

    def reload_matchers(self):
        items = self.em.get_all_originals_sorted()
        matchers = []
        for orig, vtype, eid, pseud_val, is_kept in items:
            esc = re.escape(orig)
            pattern_str = rf"(?i)(?<![a-zA-Z0-9]){esc}(?![a-zA-Z0-9])"
            try:
                rx = re.compile(pattern_str)
                matchers.append((rx, vtype, eid, pseud_val, is_kept))
            except re.error:
                pass
        self._compiled_matchers = matchers

    def anonymize_text(
        self,
        text: str,
        record_id: str,
        sender_uid: Optional[str] = None,
        thread_entity_ids: Optional[Set[str]] = None,
    ) -> str:
        if not text:
            return text

        result = text

        # Step 1: Pre-process spelled-out emails (Anti-Evasion Layer 1)
        spelled_email_rx = re.compile(
            r"\b([a-zA-Z0-9_.+-]+)\s*(?:@|\bat\b|\[at\]|\(at\)|arroba)\s*([a-zA-Z0-9-]+)\s*(?:\.|\bdot\b|\[dot\]|\(punto\)|punto)\s*([a-zA-Z]{2,})\b",
            re.IGNORECASE,
        )

        def _sub_spelled_email(m):
            # Forzamos .lower() para evitar que mayúsculas rompan la búsqueda en SQLite
            reconstructed = f"{m.group(1)}@{m.group(2)}.{m.group(3)}".lower()
            
            ent = self.em.find_entity_by_original(reconstructed)
            if ent and not ent.get("kept"):
                eid = ent["entity_id"]
                self.em.add_record(eid, record_id)
                self.em.mark_pseudonym_used(eid, "email")
                return ent["email"]
            return reconstructed

        result = spelled_email_rx.sub(_sub_spelled_email, result)

        # Step 2: Handle Slack mentions: <@UID>
        slack_mention_rx = re.compile(r"<@([A-Z0-9]+)>")

        def _sub_slack_mention(m):
            uid = m.group(1)
            ent = self.em.find_entity_by_original(uid)
            if ent and not ent.get("kept"):
                eid = ent["entity_id"]
                self.em.add_record(eid, record_id)
                self.em.mark_pseudonym_used(eid, "name")
                return ent["name"]
            return f"@{uid}"

        result = slack_mention_rx.sub(_sub_slack_mention, result)

        # Step 3: Apply registered entity replacements (Longest first)
        for rx, vtype, eid, pseud_val, is_kept in self._compiled_matchers:
            if is_kept:
                continue

            # First name scoping rule: Standalone first name ONLY matches thread participants
            if vtype == "first_name":
                if thread_entity_ids is not None and eid not in thread_entity_ids:
                    continue

            if rx.search(result):
                if vtype == "cedula":
                    ent = self.em.get_entity(eid)
                    p_val = format_cedula_with_dots(ent["cedula"]) if ent and ent.get("cedula") else pseud_val
                elif vtype == "slug":
                    p_val = slugify_name(pseud_val)
                elif vtype == "first_name":
                    ent = self.em.get_entity(eid)
                    p_val = ent["first_name"] if ent and ent.get("first_name") else pseud_val
                else:
                    p_val = pseud_val

                result = rx.sub(p_val, result)
                self.em.add_record(eid, record_id)
                field_name = vtype if vtype in {"email", "phone", "cedula", "address", "birth_iso", "plate"} else "name"
                self.em.mark_pseudonym_used(eid, field_name)

        # Step 4: Generalize quasi-identifiers (occupation + barrio + year)
        result = generalize_quasi_identifiers(result)

        return result

    def anonymize_filename(self, filename: str, record_id: str) -> str:
        if not filename:
            return filename
        name_part, ext = os.path.splitext(filename)
        anonymized_name = name_part

        for rx, vtype, eid, pseud_val, is_kept in self._compiled_matchers:
            if is_kept:
                continue
            if vtype not in ("slug", "name"):
                continue
            if rx.search(anonymized_name):
                slug = slugify_name(pseud_val)
                anonymized_name = rx.sub(slug, anonymized_name)
                self.em.add_record(eid, record_id)
                self.em.mark_pseudonym_used(eid, "name")

        return f"{anonymized_name}{ext}"


# -----------------------------------------------------------------------------
# Pipeline Ingestion & File Generation
# -----------------------------------------------------------------------------
def run_pipeline(
    sources_url: Optional[str] = None,
    token: Optional[str] = None,
    output_dir: Path = OUTPUT_DIR,
    sample_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Regenerates the complete output dataset from sources."""
    em = EntityManager()
    anonymizer = AnonymizationEngine(em)

    is_local = bool(sample_dir and sample_dir.exists())
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    output_dir.mkdir(parents=True, exist_ok=True)
    chats_out_path = output_dir / "chats.jsonl"
    docs_out_path = output_dir / "docs.jsonl"
    tables_out_path = output_dir / "tables.jsonl"
    entities_out_path = output_dir / "entities.json"

    # Ingest Clientes
    logger.info("Ingesting Clientes...")
    clientes_rows = []
    if is_local:
        clientes_csv_path = sample_dir / "input" / "tables" / "clientes.csv"
        if clientes_csv_path.exists():
            with open(clientes_csv_path, "r", encoding="latin-1") as f:
                reader = csv.DictReader(f, delimiter=";")
                clientes_rows = list(reader)
    else:
        res = requests.get(f"{sources_url}/tables/clientes.csv", headers=headers)
        if res.status_code == 200:
            content = res.content.decode("latin-1")
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            clientes_rows = list(reader)

    for r in clientes_rows:
        em.add_reserved_raw_tokens([
            r.get("nombre_completo", ""),
            r.get("correo", ""),
            r.get("num_doc", ""),
        ])

    for r in clientes_rows:
        cid = r.get("cliente_id", "")
        rec_id = f"clientes:{cid}"
        eid = em.register_person(
            name=r.get("nombre_completo", ""),
            email=r.get("correo", ""),
            phone=r.get("celular", ""),
            cedula=r.get("num_doc", ""),
            address=r.get("direccion", ""),
            birth_iso=r.get("fecha_nacimiento", ""),
            plate=re.search(r"\b[A-Z]{3}[ -]?\d{3}\b", r.get("notas", "") or "").group(0) if re.search(r"\b[A-Z]{3}[ -]?\d{3}\b", r.get("notas", "") or "") else None,
            corporate=False,
        )
        em.add_record(eid, rec_id)

    # Ingest Empleados
    logger.info("Ingesting Empleados...")
    empleados_records = []
    if not is_local and sources_url:
        res = requests.get(f"{sources_url}/tables/empleados.xml", headers=headers)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for e in root.findall("empleado"):
                rec_id = f"empleados:{e.attrib.get('id')}"
                cols = dict(e.attrib)
                for child in e:
                    cols[child.tag] = child.text or ""
                empleados_records.append((rec_id, cols))

                em.add_reserved_raw_tokens([
                    cols.get("nombre", ""),
                    cols.get("correo", ""),
                    cols.get("documento", ""),
                ])

                eid = em.register_person(
                    name=cols.get("nombre", ""),
                    email=cols.get("correo", ""),
                    phone=cols.get("celular", ""),
                    cedula=cols.get("documento", ""),
                    birth_iso=cols.get("fecha_nacimiento", ""),
                    corporate=True,
                )
                em.add_record(eid, rec_id)

    # Ingest Slack Users
    logger.info("Ingesting Slack Users...")
    users_data = []
    if is_local:
        u_path = sample_dir / "input" / "chats" / "users.json"
        if u_path.exists():
            with open(u_path, "r", encoding="utf-8") as f:
                users_data = json.load(f)
    elif sources_url:
        res = requests.get(f"{sources_url}/chats/users", headers=headers)
        if res.status_code == 200:
            users_data = res.json()

    for u in users_data:
        uid = u.get("id")
        uname = u.get("name")
        real_name = u.get("real_name") or u.get("profile", {}).get("real_name")
        email = u.get("profile", {}).get("email")
        phone = u.get("profile", {}).get("phone")
        if u.get("is_bot") or uname == "kipi":
            continue
        em.add_reserved_raw_tokens([uname, real_name, email])
        em.link_slack_user(uid, uname, real_name, email, phone)

    anonymizer.reload_matchers()

    all_output_records: Dict[str, Dict[str, Any]] = {}

    # Process Tables
    logger.info("Processing tables...")
    tables_count = 0
    with open(tables_out_path, "w", encoding="utf-8") as f_tables:
        for r in clientes_rows:
            cid = r.get("cliente_id", "")
            rec_id = f"clientes:{cid}"
            eid = em.find_entity_by_original(cid) or em.find_entity_by_original(r.get("correo", ""))
            ent = em.get_entity(eid["entity_id"]) if eid else None

            out_cols = dict(r)
            if ent:
                out_cols["nombre_completo"] = ent["name"]
                out_cols["num_doc"] = ent["cedula"]
                out_cols["correo"] = ent["email"]
                out_cols["celular"] = ent["phone"]
                out_cols["direccion"] = ent["address"]
                out_cols["fecha_nacimiento"] = ent["birth_iso"]
                em.mark_pseudonym_used(ent["entity_id"], "name")
                em.mark_pseudonym_used(ent["entity_id"], "cedula")
                em.mark_pseudonym_used(ent["entity_id"], "email")
                em.mark_pseudonym_used(ent["entity_id"], "phone")
                em.mark_pseudonym_used(ent["entity_id"], "address")
                em.mark_pseudonym_used(ent["entity_id"], "birth_iso")
                em.add_record(ent["entity_id"], rec_id)

            out_cols["ocupacion"] = generalize_occupation(r.get("ocupacion", ""))
            if r.get("notas"):
                out_cols["notas"] = anonymizer.anonymize_text(r["notas"], rec_id)

            rec = {"id": rec_id, "table": "clientes", "columns": {k: str(v) for k, v in out_cols.items()}}
            f_tables.write(json.dumps(rec, ensure_ascii=False) + "\n")
            all_output_records[rec_id] = rec
            tables_count += 1

        for rec_id, cols in empleados_records:
            out_cols = dict(cols)
            eid = em.find_entity_by_original(cols.get("correo", ""))
            ent = em.get_entity(eid["entity_id"]) if eid else None
            if ent:
                out_cols["nombre"] = ent["name"]
                out_cols["correo"] = ent["email"]
                out_cols["celular"] = ent["phone"]
                out_cols["documento"] = ent["cedula"]
                out_cols["fecha_nacimiento"] = ent["birth_iso"]
                em.mark_pseudonym_used(ent["entity_id"], "name")
                em.mark_pseudonym_used(ent["entity_id"], "email")
                em.mark_pseudonym_used(ent["entity_id"], "phone")
                em.mark_pseudonym_used(ent["entity_id"], "cedula")
                em.mark_pseudonym_used(ent["entity_id"], "birth_iso")
                em.add_record(ent["entity_id"], rec_id)

            mgr_name = cols.get("reporta_a", "")
            if mgr_name:
                mgr_ent = em.find_entity_by_original(mgr_name)
                if mgr_ent:
                    out_cols["reporta_a"] = mgr_ent["name"]

            rec = {"id": rec_id, "table": "empleados", "columns": {k: str(v) for k, v in out_cols.items()}}
            f_tables.write(json.dumps(rec, ensure_ascii=False) + "\n")
            all_output_records[rec_id] = rec
            tables_count += 1

        if not is_local and sources_url:
            res_pqr = requests.get(f"{sources_url}/tables/pqrs.xml", headers=headers)
            if res_pqr.status_code == 200:
                root_pqr = ET.fromstring(res_pqr.content)
                for p in root_pqr.findall("pqr"):
                    rec_id = f"pqrs:{p.attrib.get('radicado')}"
                    cols = dict(p.attrib)
                    for c in p:
                        cols[c.tag] = c.text or ""

                    client_eid = em.find_entity_by_original(cols.get("cliente_id", "")) or em.find_entity_by_original(cols.get("cedula", ""))
                    if client_eid:
                        cols["cedula"] = client_eid["cedula"]
                        em.add_record(client_eid["entity_id"], rec_id)
                        em.mark_pseudonym_used(client_eid["entity_id"], "cedula")

                    agent_eid = em.find_entity_by_original(cols.get("agente", ""))
                    if agent_eid:
                        cols["agente"] = slugify_name(agent_eid["name"]).replace("_", ".")
                        em.add_record(agent_eid["entity_id"], rec_id)

                    cols["descripcion"] = anonymizer.anonymize_text(cols.get("descripcion", ""), rec_id)
                    cols["respuesta"] = anonymizer.anonymize_text(cols.get("respuesta", ""), rec_id)

                    rec = {"id": rec_id, "table": "pqrs", "columns": {k: str(v) for k, v in cols.items()}}
                    f_tables.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    all_output_records[rec_id] = rec
                    tables_count += 1

            res_tx = requests.get(f"{sources_url}/tables/transacciones.csv", headers=headers)
            if res_tx.status_code == 200:
                reader_tx = csv.DictReader(io.StringIO(res_tx.content.decode("utf-8")))
                for r in reader_tx:
                    rec_id = f"transacciones:{r['tx_id']}"
                    cols = dict(r)
                    if cols.get("descripcion"):
                        cols["descripcion"] = anonymizer.anonymize_text(cols["descripcion"], rec_id)
                    rec = {"id": rec_id, "table": "transacciones", "columns": {k: str(v) for k, v in cols.items()}}
                    f_tables.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    all_output_records[rec_id] = rec
                    tables_count += 1

    anonymizer.reload_matchers()

    # Process Docs
    logger.info("Processing docs...")
    docs_count = 0
    docs_index = []
    if is_local:
        idx_path = sample_dir / "input" / "docs" / "index.json"
        if idx_path.exists():
            with open(idx_path, "r", encoding="utf-8") as f:
                docs_index = json.load(f)
    elif sources_url:
        res = requests.get(f"{sources_url}/docs", headers=headers)
        if res.status_code == 200:
            docs_index = res.json()

    with open(docs_out_path, "w", encoding="utf-8") as f_docs:
        for doc_item in docs_index:
            doc_id = doc_item["id"]
            fmt = doc_item["format"]
            filename = doc_item["filename"]

            raw_content = b""
            if is_local:
                fpath = sample_dir / "input" / "docs" / filename
                if fpath.exists():
                    raw_content = fpath.read_bytes()
            elif sources_url:
                res_doc = requests.get(f"{sources_url}/docs/{doc_id}", headers=headers)
                if res_doc.status_code == 200:
                    raw_content = res_doc.content

            anon_filename = anonymizer.anonymize_filename(filename, doc_id)
            title = ""
            body = ""
            metadata = {}

            if fmt == "md":
                text = raw_content.decode("utf-8", errors="replace")
                lines = text.splitlines(keepends=True)
                fm = {}
                body_lines = lines
                if lines and lines[0].strip() == "---":
                    fm_lines = []
                    end_idx = -1
                    for i, l in enumerate(lines[1:], start=1):
                        if l.strip() == "---":
                            end_idx = i
                            break
                        fm_lines.append(l)
                    if end_idx != -1:
                        body_lines = lines[end_idx + 1 :]
                        for fl in fm_lines:
                            if ":" in fl:
                                k, v = fl.split(":", 1)
                                fm[k.strip()] = v.strip()

                title = fm.get("title", "")
                if not title:
                    for bl in body_lines:
                        if bl.strip().startswith("# "):
                            title = bl.strip()[2:].strip()
                            break

                anon_body = anonymizer.anonymize_text(text, doc_id)
                anon_fm = {}
                for k, v in fm.items():
                    anon_fm[k] = anonymizer.anonymize_text(v, doc_id)

                metadata = anon_fm
                body = anon_body

            elif fmt == "html":
                text = raw_content.decode("utf-8", errors="replace")
                soup = BeautifulSoup(text, "html.parser")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()

                meta_tags = {}
                for m in soup.find_all("meta"):
                    m_key = m.get("name") or m.get("property")
                    if m_key and m.get("content"):
                        meta_tags[m_key] = anonymizer.anonymize_text(m["content"], doc_id)
                metadata = meta_tags
                body = anonymizer.anonymize_text(text, doc_id)

            elif fmt == "pdf":
                reader = PdfReader(io.BytesIO(raw_content))
                pdf_meta = {}
                if reader.metadata:
                    for k, v in reader.metadata.items():
                        key = k.lstrip("/").lower()
                        pdf_meta[key] = anonymizer.anonymize_text(str(v), doc_id)
                metadata = pdf_meta
                title = pdf_meta.get("title", "")

                pdf_text_parts = []
                for page in reader.pages:
                    p_text = page.extract_text() or ""
                    pdf_text_parts.append(p_text)
                body = anonymizer.anonymize_text("\n\n".join(pdf_text_parts), doc_id)

            doc_record = {
                "id": doc_id,
                "format": fmt,
                "filename": anon_filename,
                "title": title or anon_filename,
                "body": body,
                "metadata": metadata,
            }
            f_docs.write(json.dumps(doc_record, ensure_ascii=False) + "\n")
            all_output_records[doc_id] = doc_record
            docs_count += 1

    anonymizer.reload_matchers()

    # Process Chats
    logger.info("Processing chats...")
    chats_count = 0
    channels_list = []
    if is_local:
        c_path = sample_dir / "input" / "chats" / "channels.json"
        if c_path.exists():
            with open(c_path, "r", encoding="utf-8") as f:
                channels_list = json.load(f)
    elif sources_url:
        res = requests.get(f"{sources_url}/chats/channels", headers=headers)
        if res.status_code == 200:
            channels_list = res.json()

    with open(chats_out_path, "w", encoding="utf-8") as f_chats:
        for ch in channels_list:
            cname = ch["name"]
            dates = []
            if is_local:
                ch_dir = sample_dir / "input" / "chats" / cname
                if ch_dir.exists():
                    dates = [f.stem for f in ch_dir.glob("*.json")]
            elif sources_url:
                res_d = requests.get(f"{sources_url}/chats/{cname}", headers=headers)
                if res_d.status_code == 200:
                    dates = res_d.json()

            for d in dates:
                msgs = []
                if is_local:
                    msg_file = sample_dir / "input" / "chats" / cname / f"{d}.json"
                    if msg_file.exists():
                        with open(msg_file, "r", encoding="utf-8") as f:
                            msgs = json.load(f)
                elif sources_url:
                    res_m = requests.get(f"{sources_url}/chats/{cname}/{d}", headers=headers)
                    if res_m.status_code == 200:
                        msgs = res_m.json()

                # Collect thread participants for first-name scoping
                thread_participants: Dict[str, Set[str]] = {}
                for m in msgs:
                    tts = m.get("thread_ts") or m.get("ts")
                    if tts not in thread_participants:
                        thread_participants[tts] = set()
                    u = m.get("user")
                    if u and u != "UKIPIBOT01":
                        ue = em.find_entity_by_original(u)
                        if ue:
                            thread_participants[tts].add(ue["entity_id"])

                for m in msgs:
                    msg_id = m.get("client_msg_id") or m.get("ts")
                    uid = m.get("user")
                    thread_ts = m.get("thread_ts") or m.get("ts")
                    thread_id = f"{cname}:{thread_ts}"

                    author_name = "Kipi"
                    sender_eid = None
                    if uid != "UKIPIBOT01" and m.get("subtype") != "bot_message":
                        author_ent = em.find_entity_by_original(uid)
                        if author_ent:
                            author_name = author_ent["name"]
                            sender_eid = author_ent["entity_id"]
                            em.add_record(author_ent["entity_id"], msg_id)
                            em.mark_pseudonym_used(author_ent["entity_id"], "name")

                    active_thread_eids = thread_participants.get(thread_ts, set())
                    anon_text = anonymizer.anonymize_text(
                        m.get("text", ""),
                        msg_id,
                        sender_uid=uid,
                        thread_entity_ids=active_thread_eids,
                    )

                    attachments = []
                    for f_item in m.get("files", []):
                        fname = f_item.get("name") or f_item.get("filename") or ""
                        anon_fname = anonymizer.anonymize_filename(fname, msg_id)
                        attachments.append({"filename": anon_fname})

                    chat_rec = {
                        "id": msg_id,
                        "thread_id": thread_id,
                        "author": author_name,
                        "ts": m.get("ts", ""),
                        "text": anon_text,
                        "attachments": attachments,
                    }
                    f_chats.write(json.dumps(chat_rec, ensure_ascii=False) + "\n")
                    all_output_records[msg_id] = chat_rec
                    chats_count += 1

    # Export entities.json passing all_output_records for strict containment validation
    logger.info("Writing entities.json...")
    entities_data = em.export_entities_json(all_output_records=all_output_records)
    with open(entities_out_path, "w", encoding="utf-8") as f_ent:
        json.dump(entities_data, f_ent, ensure_ascii=False, indent=2)

    logger.info(f"Pipeline complete! Chats={chats_count}, Docs={docs_count}, Tables={tables_count}")
    return {
        "chats": chats_count,
        "docs": docs_count,
        "tables": tables_count,
    }


def anonymize_live_batch(
    source: str,
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Anonymizes an incoming batch of live records in real time (< 60s) for POST /anonymize."""
    em = EntityManager()
    anonymizer = AnonymizationEngine(em)

    anonymized_records = []
    used_entity_ids: Set[str] = set()

    for r in records:
        rec_id = r.get("id", "")
        if source == "chats":
            out_r = dict(r)
            author_orig = r.get("author", "")
            author_ent = em.find_entity_by_original(author_orig)
            if not author_ent and author_orig not in {"Kipi", "kipi"}:
                eid = em.register_person(author_orig)
                anonymizer.reload_matchers()
                author_ent = em.get_entity(eid)
            if author_ent and not author_ent.get("kept"):
                out_r["author"] = author_ent["name"]
                em.add_record(author_ent["entity_id"], rec_id)
                em.mark_pseudonym_used(author_ent["entity_id"], "name")
                used_entity_ids.add(author_ent["entity_id"])

            out_r["text"] = anonymizer.anonymize_text(r.get("text", ""), rec_id)

            anon_attachments = []
            for att in r.get("attachments", []):
                fn = att.get("filename", "")
                anon_fn = anonymizer.anonymize_filename(fn, rec_id)
                anon_attachments.append({"filename": anon_fn})
            out_r["attachments"] = anon_attachments
            anonymized_records.append(out_r)

        elif source == "docs":
            out_r = dict(r)
            out_r["filename"] = anonymizer.anonymize_filename(r.get("filename", ""), rec_id)
            out_r["body"] = anonymizer.anonymize_text(r.get("body", ""), rec_id)
            anon_meta = {}
            for k, v in r.get("metadata", {}).items():
                anon_meta[k] = anonymizer.anonymize_text(str(v), rec_id)
            out_r["metadata"] = anon_meta
            anonymized_records.append(out_r)

        elif source == "tables":
            out_r = dict(r)
            tbl = r.get("table", "")
            cols = dict(r.get("columns", {}))

            if tbl == "clientes":
                orig_name = cols.get("nombre_completo", "")
                orig_email = cols.get("correo", "")
                orig_phone = cols.get("celular", "")
                orig_doc = cols.get("num_doc", "")

                ent = em.find_entity_by_original(orig_doc) or em.find_entity_by_original(orig_email)
                if not ent:
                    eid = em.register_person(
                        name=orig_name,
                        email=orig_email,
                        phone=orig_phone,
                        cedula=orig_doc,
                        address=cols.get("direccion"),
                        birth_iso=cols.get("fecha_nacimiento"),
                    )
                    anonymizer.reload_matchers()
                    ent = em.get_entity(eid)

                if ent:
                    cols["nombre_completo"] = ent["name"]
                    cols["num_doc"] = ent["cedula"]
                    cols["correo"] = ent["email"]
                    cols["celular"] = ent["phone"]
                    cols["direccion"] = ent["address"]
                    cols["fecha_nacimiento"] = ent["birth_iso"]
                    em.mark_pseudonym_used(ent["entity_id"], "name")
                    em.mark_pseudonym_used(ent["entity_id"], "cedula")
                    em.mark_pseudonym_used(ent["entity_id"], "email")
                    em.mark_pseudonym_used(ent["entity_id"], "phone")
                    em.mark_pseudonym_used(ent["entity_id"], "address")
                    em.mark_pseudonym_used(ent["entity_id"], "birth_iso")
                    em.add_record(ent["entity_id"], rec_id)
                    used_entity_ids.add(ent["entity_id"])

                cols["ocupacion"] = generalize_occupation(cols.get("ocupacion", ""))
                if cols.get("notas"):
                    cols["notas"] = anonymizer.anonymize_text(cols["notas"], rec_id)

            elif tbl == "empleados":
                orig_name = cols.get("nombre", "")
                orig_email = cols.get("correo", "")
                ent = em.find_entity_by_original(orig_email) or em.find_entity_by_original(orig_name)
                if not ent:
                    eid = em.register_person(orig_name, email=orig_email, corporate=True)
                    anonymizer.reload_matchers()
                    ent = em.get_entity(eid)
                if ent:
                    cols["nombre"] = ent["name"]
                    cols["correo"] = ent["email"]
                    cols["celular"] = ent["phone"]
                    cols["documento"] = ent["cedula"]
                    em.mark_pseudonym_used(ent["entity_id"], "name")
                    em.mark_pseudonym_used(ent["entity_id"], "email")
                    em.mark_pseudonym_used(ent["entity_id"], "phone")
                    em.mark_pseudonym_used(ent["entity_id"], "cedula")
                    em.add_record(ent["entity_id"], rec_id)
                    used_entity_ids.add(ent["entity_id"])

            else:
                for k, v in cols.items():
                    if isinstance(v, str):
                        cols[k] = anonymizer.anonymize_text(v, rec_id)

            out_r["columns"] = {k: str(v) for k, v in cols.items()}
            anonymized_records.append(out_r)

    # Collect used entities
    all_entities_export = em.export_entities_json()["entities"]
    used_entities = [
        e for e in all_entities_export
        if e["entity_id"] in used_entity_ids or any(r.get("id") in e.get("records", []) for r in records)
    ]

    return anonymized_records, used_entities
