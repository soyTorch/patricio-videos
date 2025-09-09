# Configuración de Credenciales de Google Drive

## Requisitos

Para que la aplicación funcione correctamente, necesitas configurar las credenciales de Google Drive.

## Configuración Local

1. **Archivo JSON**: Coloca tu archivo de credenciales de servicio de Google Drive en la raíz del proyecto con el nombre:
   ```
   video-generator-471617-b782bb619dcc.json
   ```

2. **Variable de entorno**: Alternativamente, puedes usar la variable de entorno:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/ruta/a/tu/archivo/credenciales.json"
   ```

## Configuración en Producción

Para despliegue en producción, usa la variable de entorno:

```bash
export GDRIVE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

## Estructura del Archivo de Credenciales

El archivo JSON debe tener la siguiente estructura:

```json
{
  "type": "service_account",
  "project_id": "tu-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "nombre@proyecto.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "...",
  "universe_domain": "googleapis.com"
}
```

## Verificación

Para verificar que las credenciales funcionan, ejecuta:

```bash
python3 -c "from app.main import _maybe_get_drive_service; print('✅ OK' if _maybe_get_drive_service() else '❌ Error')"
```

## Seguridad

⚠️ **IMPORTANTE**: Nunca commitees archivos de credenciales al repositorio. Están incluidos en `.gitignore` por seguridad.
