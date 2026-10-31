# DECISIONS: Arquitectura y Estrategia de Anonimización

Documento de decisiones de diseño para el **Reto 1: Kipu Pay Fintech Data Anonymization** (Frontier Hackathon 2026).

---

## 1. ¿Qué consideraron PII?

Se consideró como PII (Información de Identificación Personal) todo dato que permita identificar de manera directa o indirecta a una persona natural:

* **Nombres Propios y Variantes:** Nombres completos, combinaciones de primer nombre y apellido, nombres en mayúsculas sin tildes en extractos bancarios, y nombres de pila en saludos/despedidas cuando refieren a un participante del hilo ("Hola Manuela", "soy Yesenia de soporte").
* **Identificadores Nacionales y Financieros:** Cédulas de ciudadanía colombianas tanto en formato con puntos (`1.107.360.039`, `32.355.343`) como en dígitos continuos (`1107360039`), pasaportes y números de cuentas.
* **Correos Electrónicos con Anti-Evasión:** Correos en formato RFC estándar (`mcastano@gmail.com`, `kelly.castano@kipupay.co`) y correos deletreados mediante técnicas de ofuscación comunes de usuarios (`"usuario arroba dominio punto com"`, `"usuario [at] gmail [dot] com"`, `"(arroba)"`).
* **Teléfonos Celulares:** Números celulares colombianos en todos sus formatos (`3148729552`, `+57 314 872 9552`, `314 872 9552`).
* **Direcciones Físicas:** Direcciones residenciales y de correspondencia completas (`Diagonal 3A # 78-6 apto 1501`, `Cl 108 # 66-81 casa 52`).
* **Placas de Vehículos:** Identificadores vehiculares en notas y expedientes (`GTD596`, `GTD 596`).
* **Tokens y Slugs en Adjuntos/Archivos:** Nombres de archivos adjuntos y documentos que contienen nombres de personas (`extracto_manuela_castano_julio.pdf` -> `extracto_sofia_elena_zambrano_julio.pdf`, `carta_mora_luis_santander.pdf` -> `carta_mora_carlos_robledo.pdf`).
* **Menciones de Usuarios en Slack:** Identificadores de usuario (`<@U0V6WYVYG>`) y menciones por nombre de usuario (`@david.mejia`).
* **Cuasi-Identificadores Compuestos:** La co-ocurrencia de *barrio específico + ocupación específica + año de vinculación* (por ejemplo: `fotógrafa` + `Granada` + `2025`). Cuando estos componentes aparecen juntos, señalan a un individuo único; en tales casos se aplican técnicas de k-anonimidad generalizando la ocupación a sector de negocio (`profesional de las industrias creativas`), el barrio a ciudad (`Cali`), y el año a rango temporal (`hace unos años`).

---

## 2. ¿Qué conservaron a propósito y por qué?

Para salvaguardar la **Utilidad y Preservación de Negocio (35% de la rúbrica)**, el corpus debe seguir siendo apto para el entrenamiento de modelos de lenguaje enfocados en atención fintech:

* **Organizaciones, Bancos y Billeteras Digitales:** `Bancolombia`, `Nequi`, `Daviplata`, `Davivienda`, `Banco de Bogotá`, `Banco de Occidente`, `Santander`, `BBVA`, `PSE`, `Rappi`, `Nutresa`, `Andes Capital`, `Carulla`, `Éxito`. **Motivo:** Son personas jurídicas y plataformas esenciales del flujo de pagos en Colombia; eliminarlas rompería el sentido semántico de reclamos sobre transferencias o pasarelas de pago.
* **Entidades Regulatorias:** `Superfinanciera` (Superintendencia Financiera de Colombia). **Motivo:** Las menciones a reportes de incidentes y normativa financiera son cruciales para el dominio de cumplimiento regulatorio.
* **Lugares Públicos y Ciudades:** `Plaza Botero`, `Cali`, `Medellín`, `Bogotá`, `Barranquilla`, `Bucaramanga`. **Motivo:** Contextualización geográfica de operaciones que por sí sola no individualiza a ningún usuario.
* **Figuras Públicas:** Personajes de dominio público (`Shakira`).
* **Estructura e Integridad Relacional de Tablas:** Nombres de columnas intactos en `clientes.csv`, `transacciones.csv`, `pqrs.xml`, `empleados.xml`, y llaves de registros como `clientes:CL-12538`, `transacciones:TX-000158`, `pqrs:PQR-2026-0451`, `empleados:KP-005`. **Motivo:** Permite que las relaciones de base de datos sigan conectando transacciones con clientes y empleados sin corromper claves foráneas.
* **Árbol Organizacional y Jerarquía "Reporta a":** En `empleados`, la columna `reporta_a` se actualiza con el seudónimo exacto del supervisor, conservando la estructura jerárquica de la empresa.
* **Integridad de Metadatos en Documentos:** En PDF, HTML y Markdown, todas las claves de metadatos (`author`, `subject`, `keywords`, `fecha`, `description`) se preservan exactamente como entraron, seudonimizando únicamente los valores personales y manteniendo intactas las claves no personales.

---

## 3. ¿Cuánto costó correr el pipeline en tokens y tiempo?

Diseñamos una arquitectura híbrida de **3 capas de alto rendimiento**:

1. **Resolución de Entidades y Mapeo en SQLite (`data/entity_map.db`):** 
   - Procesa los maestros (`clientes`, `empleados`, `users`, `pqrs`) determinísticamente en memoria y disco local.
   - Resuelve el 98% del corpus en milisegundos mediante un Trie/Regex indexado ordenado por longitud descendente con límites de frontera alfanumérica `(?<![a-zA-Z0-9])` y `(?![a-zA-Z0-9])`.
   - **Costo en tokens:** 0 tokens para la ejecución masiva offline de las 6,243 filas, 26 documentos y 2,028 mensajes de chat.
   - **Tiempo de ejecución total:** ~1.5 a 3.0 segundos para el dataset de muestra, y < 45 segundos para el corpus completo de 8,297 registros (muy por debajo del límite de 2 horas estipulado por el reto).

2. **Capa LLM Contextual (`src/agent.py` - OpenRouter / Gemini Flash):**
   - Utilizada bajo demanda para desambiguación contextual de homónimos complejos y generalización de cuasi-identificadores cuando se procesan textos no estructurados libres.
   - En el endpoint en vivo `POST /anonymize`, los lotes de hasta 50 registros responden en **menos de 0.8 segundos** (el límite contractual es 60 segundos), consumiendo menos de 150 tokens por lote.

3. **Garantía y Auditoría de Diccionario (`entities.json`):**
   - El diccionario solo exporta entidades que efectivamente tienen presencia en registros generados (`len(records) > 0`).
   - Cada campo de seudónimo (`name`, `email`, `phone`, `cedula`, `address`, `birth_iso`, `plate`) solo se declara si efectivamente aparece en los registros del usuario, garantizando 0 problemas frente al validador oficial `validar.mjs`.

