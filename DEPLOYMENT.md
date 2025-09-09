# Despliegue en Dokploy

Esta guía te ayudará a desplegar la aplicación Video Render API en tu servidor usando Dokploy.

## 📋 Requisitos previos

1. **Dokploy instalado** en tu servidor
2. **Credenciales de Google Drive** (archivo JSON)
3. **Acceso al repositorio** desde tu servidor

## 🚀 Pasos para el despliegue

### 1. Crear nueva aplicación en Dokploy

1. Accede a tu panel de Dokploy
2. Crea una nueva aplicación
3. Selecciona **"Docker"** como tipo de despliegue
4. Configura el repositorio: `https://github.com/soyTorch/patricio-videos.git`

### 2. Configurar variables de entorno

En la configuración de la aplicación, añade estas variables de entorno:

#### Variables obligatorias:
```bash
# API Key para autenticación
API_KEY=tu_api_key_super_segura_aqui

# Credenciales de Google Drive (contenido completo del JSON)
GDRIVE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"video-generator-471617",...}
```

#### Variables opcionales:
```bash
# Puerto (por defecto 8023)
PORT=8023

# Host (por defecto 0.0.0.0)
HOST=0.0.0.0

# Timezone
GENERIC_TIMEZONE=Europe/Madrid
```

### 3. Configurar el archivo JSON de credenciales

**Opción A: Variable de entorno (Recomendado)**
1. Copia todo el contenido del archivo `video-generator-471617-b782bb619dcc.json`
2. Pégalo como valor de la variable `GDRIVE_SERVICE_ACCOUNT_JSON`

**Opción B: Archivo en el contenedor**
1. Sube el archivo JSON al servidor
2. Monta el archivo como volumen en el contenedor
3. Configura `GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json`

### 4. Configurar puerto y networking

- **Puerto interno**: 8023 (definido en Dockerfile)
- **Puerto externo**: El que prefieras (ej: 8080, 443, etc.)
- **Protocolo**: HTTP/HTTPS

### 5. Configurar recursos (opcional)

Recursos recomendados:
- **CPU**: 1-2 vCPU
- **RAM**: 2-4 GB
- **Almacenamiento**: 10-20 GB

## 🧪 Verificar el despliegue

Una vez desplegado, verifica que funciona:

```bash
# Health check
curl https://tu-dominio.com/health

# Deberías recibir: {"ok":true}
```

### Prueba completa
```bash
curl -X POST https://tu-dominio.com/render \
  -H "Authorization: Bearer tu_api_key_aqui" \
  -F "video_url=https://drive.google.com/file/d/TU_FILE_ID" \
  -F "audio_url=https://drive.google.com/file/d/TU_AUDIO_ID" \
  -F "overlay_text=Test Video" \
  -F "target=vertical" \
  --output test_video.mp4
```

## 🔧 Configuración avanzada

### Variables de entorno completas

```bash
# Obligatorias
API_KEY=tu_api_key_super_segura
GDRIVE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}

# Opcionales
PORT=8023
HOST=0.0.0.0
GENERIC_TIMEZONE=Europe/Madrid
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
```

### Logs y debugging

Para ver logs de la aplicación:
```bash
# En Dokploy, ve a la sección "Logs" de tu aplicación
# O usa Docker directamente:
docker logs tu-contenedor-id -f
```

### Escalado

Para mayor rendimiento:
- Aumenta RAM a 4-8 GB
- Aumenta CPU a 2-4 vCPU
- Considera usar múltiples instancias con load balancer

## 🔒 Seguridad

1. **Cambia el API_KEY** por algo seguro
2. **Usa HTTPS** en producción
3. **Restringe acceso** por IP si es posible
4. **Monitorea logs** regularmente

## 🐛 Troubleshooting

### Error: "Google Drive service not available"
- Verifica que `GDRIVE_SERVICE_ACCOUNT_JSON` esté correctamente configurada
- Asegúrate de que el JSON sea válido

### Error: "Address already in use"
- Cambia el puerto en la variable `PORT`
- Verifica que no haya conflictos de puertos

### Error: "FFmpeg not found"
- El Dockerfile ya incluye FFmpeg
- Si persiste, verifica que el contenedor se construyó correctamente

### Videos no se generan
- Verifica que los archivos de Google Drive sean públicos o accesibles
- Revisa los logs para errores específicos
- Asegúrate de que hay suficiente espacio en disco

## 📞 Soporte

Si encuentras problemas, revisa:
1. Logs de la aplicación en Dokploy
2. Variables de entorno configuradas
3. Conectividad a Google Drive
4. Recursos del servidor (RAM, CPU, disco)
