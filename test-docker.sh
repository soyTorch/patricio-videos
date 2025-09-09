#!/bin/bash

echo "🐳 Probando despliegue con Docker..."
echo "===================================="

# Detener contenedor existente si existe
echo "🛑 Deteniendo contenedor existente..."
docker stop video-render-api 2>/dev/null || true
docker rm video-render-api 2>/dev/null || true

# Construir imagen
echo "🔨 Construyendo imagen Docker..."
docker build -t video-render-api:latest .

if [ $? -ne 0 ]; then
    echo "❌ Error construyendo la imagen"
    exit 1
fi

echo "✅ Imagen construida exitosamente"

# Verificar que existe el archivo de credenciales
if [ ! -f "video-generator-471617-b782bb619dcc.json" ]; then
    echo "❌ Archivo de credenciales no encontrado"
    echo "   Asegúrate de que video-generator-471617-b782bb619dcc.json existe"
    exit 1
fi

# Leer credenciales JSON
GDRIVE_CREDS=$(cat video-generator-471617-b782bb619dcc.json | jq -c .)

# Ejecutar contenedor
echo "🚀 Ejecutando contenedor..."
docker run -d \
  --name video-render-api \
  -p 8023:8023 \
  -e API_KEY="test_api_key_123" \
  -e GDRIVE_SERVICE_ACCOUNT_JSON="$GDRIVE_CREDS" \
  -e PYTHONUNBUFFERED=1 \
  video-render-api:latest

if [ $? -ne 0 ]; then
    echo "❌ Error ejecutando el contenedor"
    exit 1
fi

echo "✅ Contenedor ejecutándose"

# Esperar a que la aplicación se inicie
echo "⏳ Esperando a que la aplicación se inicie..."
sleep 10

# Verificar health check
echo "🏥 Verificando health check..."
response=$(curl -s http://localhost:8023/health)

if [ "$response" = '{"ok":true}' ]; then
    echo "✅ Health check exitoso: $response"
else
    echo "❌ Health check falló: $response"
    echo "📋 Logs del contenedor:"
    docker logs video-render-api --tail 20
    exit 1
fi

# Prueba de generación de video (opcional)
echo ""
echo "🎬 ¿Quieres probar la generación de video? (y/N)"
read -r test_video

if [[ $test_video =~ ^[Yy]$ ]]; then
    echo "🎥 Probando generación de video..."
    
    curl -X POST http://localhost:8023/render \
      -H "Authorization: Bearer test_api_key_123" \
      -F "video_url=https://drive.google.com/file/d/1impzAX_UznRi7_ou4uJZrW_VpCE_PICR/view?usp=sharing" \
      -F "audio_url=https://drive.google.com/file/d/1p8AbYHdXD9Mf8uaS6uOmisuHESZhKtl0/view?usp=drive_link" \
      -F "overlay_text=Docker Test Video" \
      -F "target=vertical" \
      --output docker_test_video.mp4 \
      --progress-bar
    
    if [ -f "docker_test_video.mp4" ] && [ -s "docker_test_video.mp4" ]; then
        file_size=$(stat -f%z docker_test_video.mp4 2>/dev/null || stat -c%s docker_test_video.mp4)
        echo "✅ Video generado exitosamente: docker_test_video.mp4 ($file_size bytes)"
    else
        echo "❌ Error generando video"
    fi
fi

echo ""
echo "📊 Estado del contenedor:"
docker ps | grep video-render-api

echo ""
echo "🎉 ¡Prueba de Docker completada!"
echo ""
echo "📝 Para desplegar en Dokploy:"
echo "1. Sube el código a tu repositorio"
echo "2. En Dokploy, crea una nueva aplicación Docker"
echo "3. Configura las variables de entorno:"
echo "   - API_KEY=tu_api_key_segura"
echo "   - GDRIVE_SERVICE_ACCOUNT_JSON=[JSON de credenciales]"
echo "4. Despliega la aplicación"
echo ""
echo "🛑 Para detener el contenedor de prueba:"
echo "   docker stop video-render-api"
echo "   docker rm video-render-api"
