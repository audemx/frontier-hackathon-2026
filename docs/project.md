# Reto 1: Vende los datos sin vender a la gente

## Brief

Anonimiza el corpus de soporte de una fintech para venderlo: que no se fugue nadie, que siga sirviendo para entrenar y que cada persona sea una sola de punta a punta.

Kipu Pay es una fintech colombiana de crédito y pagos. Tiene conversaciones de soporte, documentos internos y tablas de clientes y transacciones, y un comprador dispuesto a pagar por ese corpus para entrenar modelos de atención al cliente. El trato solo se cierra si los datos siguen siendo útiles para entrenar y ninguna persona real queda expuesta.

Tu equipo entrega esa versión del corpus: la misma información de negocio y las mismas conversaciones, sin que nadie pueda saber quién es quién. Hay nombres en mayúsculas sin tildes dentro de extractos, correos deletreados con "arroba" y "punto", placas, pasaportes, metadatos de PDF, comentarios HTML, menciones de Slack, dos clientas con el mismo nombre completo y combinaciones de barrio, ocupación y año que identifican a alguien sin decir su nombre.

Las fuentes llegan por el API de fuentes con tu token (2.028 mensajes, 26 documentos y 6.243 filas). Tu solución es un servicio HTTP que regenera output/ desde ese API y anonimiza registros nuevos en vivo. El jurado es un programa: puntúa fuga (45), utilidad (35) y consistencia (20). El enunciado completo, los contratos y el validador vienen en el material del reto.

## Restricciones

- Puedes usar cualquier modelo, librería o herramienta, incluidos LLMs por API. No vale un servicio o una librería que anonimice PII como producto terminado (AWS Comprehend PII, Presidio, Private AI y similares).
- La salida es uno a uno con la entrada: cada registro aparece una vez, con su mismo id.
- La misma persona recibe el mismo seudónimo en todas las fuentes; dos personas con el mismo nombre reciben seudónimos distintos.
- El seudónimo conserva la categoría del original: nombre por nombre del mismo género, correo por correo, cédula por cédula con formato válido.
- Organizaciones, lugares, marcas y figuras públicas se conservan.
- Tu servicio regenera la salida en menos de 2 horas y responde /anonymize en menos de 60 segundos por lote de 50.
- Tienes tres corridas de evaluación: cada VALIDAR ENTRYPOINT que pasa gasta una.

## Entregables

### SYSTEMS DESIGN
- Doc de diseño (una página, pdf o enlace)
- Diagrama de arquitectura (imagen, pdf o enlace)

### EJECUCIÓN
- Repo (url pública)
- Entrypoint (url pública del servicio desplegado, con get /health y el token del equipo)
- Video de 2 minutos (enlace público, máximo 2 minutos)

### DEMO DAY
- Material del pitch (slides, pdf o enlace), opcional

### CONTRATO DEL ENTRYPOINT

Desplegado por tu equipo, accesible desde internet desde las 19:00 hasta que termine el demo day. Todas las llamadas llevan Authorization: Bearer <token>. Despliégalo donde quieras.

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| GET | /health | Responde 200 con {status: "ok", team, version, models}. |
| POST | /run | Recibe {sources_url, token}, regenera output/ desde el API de fuentes y devuelve un job_id. |
| GET | /run/{job_id} | Estado del job: queued, running, done o failed. |
| GET | /output/{archivo} | chats.jsonl, docs.jsonl, tables.jsonl o entities.json de la última corrida terminada. |
| POST | /anonymize | Recibe {source, records} y devuelve los mismos ids anonimizados más las entidades que intervinieron. |
| GET | /entities | El diccionario completo de la última corrida. |