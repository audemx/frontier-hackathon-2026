#!/usr/bin/env bash
set -e
# =====================================================================================
# Crear entorno virtual e instalar dependencias
# =====================================================================================

python3 -m venv .venv

# Actualizar pip usando el binario del entorno directamente
./.venv/bin/python -m pip install --upgrade pip

# Instalar dependencias
./.venv/bin/pip install -r requirements.txt

# Registrar el kernel para Jupyter
./.venv/bin/python -m ipykernel install --user --name=frontier-venv --display-name "Python (Frontier Hackathon)"

echo "¡Entorno de desarrollo listo y aislado con éxito!"

# =====================================================================================
# Descargar el sample.zip
# =====================================================================================

# Cargar variables del archivo .env de forma segura
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Validar que el token exista
if [ -z "$FUENTES_TOKEN" ]; then
    echo "❌ Error: La variable FUENTES_TOKEN no está definida en el archivo .env"
    exit 1
fi

echo "🚀 Conectando a: $FUENTES_URL"
echo "📥 Descargando sample.zip..."

# Ejecutar curl con la cabecera de autorización Bearer
curl -s -H "Authorization: Bearer $FUENTES_TOKEN" \
     "$FUENTES_URL/sample.zip" \
     -o sample.zip

echo "✅ ¡Descarga exitosa! Archivo 'sample.zip' guardado en la raíz."

# =====================================================================================
# Verificación de Setup (Frontier)
# =====================================================================================

echo "🔍 Ejecutando verificación de setup con pi agent..."
pi --provider openrouter --model openai/gpt-4o-mini -p "Responde solo con: FRONTIER-994D8B" 2>&1 | curl -fsS --data-binary @- https://frontier.lab10.ai/api/setup/994d8bde-d936-4095-898c-0d04d5ae102a

echo "✨ ¡Setup verificado y reportado a Frontier con éxito!"