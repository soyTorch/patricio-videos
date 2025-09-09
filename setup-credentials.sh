#!/bin/bash

echo "🔧 Script de configuración de credenciales para Dokploy"
echo "======================================================"

# Verificar si existe el archivo de credenciales
CREDS_FILE="video-generator-471617-b782bb619dcc.json"

if [ -f "$CREDS_FILE" ]; then
    echo "✅ Archivo de credenciales encontrado: $CREDS_FILE"
    
    # Leer el contenido del archivo y escapar para uso en variable de entorno
    echo ""
    echo "📋 Contenido para la variable GDRIVE_SERVICE_ACCOUNT_JSON:"
    echo "========================================================="
    
    # Mostrar el JSON compactado para copiar como variable de entorno
    cat "$CREDS_FILE" | jq -c .
    
    echo ""
    echo "📝 Instrucciones:"
    echo "1. Copia el JSON de arriba (toda la línea)"
    echo "2. En Dokploy, ve a tu aplicación > Variables de entorno"
    echo "3. Añade una nueva variable:"
    echo "   Nombre: GDRIVE_SERVICE_ACCOUNT_JSON"
    echo "   Valor: [pega el JSON copiado]"
    echo ""
    echo "4. También añade:"
    echo "   Nombre: API_KEY"
    echo "   Valor: [tu_api_key_segura]"
    echo ""
    
    # Verificar que el JSON es válido
    if jq empty "$CREDS_FILE" 2>/dev/null; then
        echo "✅ El archivo JSON es válido"
    else
        echo "❌ ERROR: El archivo JSON no es válido"
        exit 1
    fi
    
else
    echo "❌ Archivo de credenciales no encontrado: $CREDS_FILE"
    echo ""
    echo "📥 Para obtener las credenciales:"
    echo "1. Ve a Google Cloud Console"
    echo "2. Selecciona tu proyecto"
    echo "3. Ve a IAM & Admin > Service Accounts"
    echo "4. Crea o selecciona una cuenta de servicio"
    echo "5. Genera una nueva clave JSON"
    echo "6. Descarga el archivo y renómbralo a: $CREDS_FILE"
    echo "7. Ejecuta este script nuevamente"
    exit 1
fi

echo "🚀 ¡Listo para desplegar en Dokploy!"
