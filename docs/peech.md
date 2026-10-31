# Strategic Architecture

## 1. The Challenge: The "Juan Pérez" Trap
In real-world fintech datasets (like Kipu Pay's support corpus and transaction tables), name collisions are inevitable. Multiple independent customers will share the exact same full name (e.g., two different individuals named "Juan Pérez"). 

If a naive anonymization pipeline maps data *solely by string matching* (every time it sees "Juan Pérez", it replaces it with "Carlos Gómez"), two catastrophic failures occur:
1. **Data Corruption (Loss of Utility):** Two distinct real-world customers are merged into a single synthetic entity, corrupting transaction histories and support behavior patterns.
2. **Consistency Penalties:** The evaluation rubric explicitly demands that *two people with the same name receive distinct pseudonyms*, while *the exact same person retains their assigned pseudonym globally* across Slack, PDF metadata, and SQL tables.

---

## 2. Our Solution: Unique Entity Fingerprinting & Stateful Mapping

To achieve a 100% score on the consistency rubric without leaking data, our engine separates **display names** from **unique entity identifiers** using a persistent local SQLite mapping state (`data/entity_map.db`).

### A. The Entity Fingerprint Strategy
Instead of mapping names directly, our pipeline maps cryptographic hashes of **unique structural identifiers** (such as `user_id`, authentic account numbers, or unique contextual hashes for unstructured text):
* **Real Entity A (`user_id: 1001`, Name: Juan Pérez)** $\rightarrow$ Mapped to Pseudonym: `Carlos Gómez`
* **Real Entity B (`user_id: 2045`, Name: Juan Pérez)** $\rightarrow$ Mapped to Pseudonym: `Roberto Sánchez`

Even though both customers share the identical real name, their distinct underlying structural IDs guarantee separate, unique synthetic profiles.

### B. Handling Unstructured Text (Slack / PDFs without IDs)
For conversational text where a direct database ID might be absent:
1. The engine extracts contextual proximity anchors (e.g., associated email hashes, support ticket IDs, or channel metadata).
2. It generates a deterministic contextual fingerprint: `hash(Name + Context Anchor)`.
3. This ensures that mentions of the same individual within a conversation thread resolve consistently to the same pseudonym.

---

## 3. Live Batch Processing (`POST /anonymize`)
When the automated judge submits incoming batches of 50 new records in real time:
1. **Lookup Phase:** The pipeline inspects the incoming record's entity fingerprint against our local SQLite state database (`entity_map.db`).
2. **Known Entity:** If the fingerprint already exists in the state store, the engine instantly retrieves the previously assigned pseudonym, guaranteeing global consistency with the historical corpus.
3. **New Entity:** If the fingerprint is entirely new, the pipeline generates a valid synthetic profile (preserving gender, valid document format, and category), saves it to the state database for future lookups, and applies it to the record.