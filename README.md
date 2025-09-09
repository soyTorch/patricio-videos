# Video Render API

API REST para procesar videos añadiendo audio y texto superpuesto usando FFmpeg.

## Características

- 🎬 Procesamiento de videos con FFmpeg
- 🎵 Mezcla o reemplazo de audio
- 📝 Superposición de texto configurable
- 🔒 Autenticación con API Key
- 🐳 Containerizado con Docker
- 📏 Redimensionamiento de videos
- ⚡ Respuesta streaming para archivos grandes

## Instalación

### Con Docker (Recomendado)

```bash
# Construir la imagen
docker build -t video-render-api .

# Ejecutar el contenedor
docker run -p 8023:8023 -e API_KEY="tu_api_key_secreta" video-render-api
```

### Instalación local

```bash
# Instalar dependencias
pip install -r requirements.txt

# Configurar API Key
export API_KEY="tu_api_key_secreta"

# Ejecutar la aplicación
uvicorn app.main:app --host 0.0.0.0 --port 8023
```

## Uso

### Endpoints disponibles

- `GET /health` - Verificar estado de la API
- `POST /render` - Procesar video con audio y texto

### Ejemplo de uso con curl

```bash
curl -X POST "http://localhost:8023/render" \
  -H "Authorization: Bearer tu_api_key_secreta" \
  -F "video=@video.mp4" \
  -F "audio=@audio.mp3" \
  -F "overlay_text=Mi texto personalizado" \
  -F "position=bottom" \
  -F "mix_audio=false" \
  -F "target=1920x1080" \
  -F "crf=18" \
  --output resultado.mp4
```

### Parámetros del endpoint /render

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `video` | File | ✅ | Archivo de video a procesar |
| `audio` | File | ✅ | Archivo de audio a añadir |
| `overlay_text` | String | ❌ | Texto a superponer (default: "") |
| `position` | String | ❌ | Posición del texto: `top`, `center`, `bottom` (default: "bottom") |
| `mix_audio` | String | ❌ | Mezclar con audio original: `true`/`false` (default: "false") |
| `target` | String | ❌ | Resolución de salida: `original`, `1920x1080`, etc. (default: "original") |
| `crf` | Integer | ❌ | Calidad del video: 18-28 (default: 18) |

### Autenticación

La API requiere un token Bearer en el header `Authorization`:

```bash
Authorization: Bearer tu_api_key_secreta
```

Configura la API key usando la variable de entorno `API_KEY`.

## Configuración

### Variables de entorno

- `API_KEY`: Clave de API para autenticación (default: "change_me")

## Desarrollo

### Estructura del proyecto

```
.
├── app/
│   └── main.py          # Aplicación principal FastAPI
├── Dockerfile           # Configuración Docker
├── requirements.txt     # Dependencias Python
└── README.md           # Documentación
```

### Ejecutar en modo desarrollo

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8023 --reload
```

### Documentación interactiva

Una vez ejecutando, visita:
- Swagger UI: http://localhost:8023/docs
- ReDoc: http://localhost:8023/redoc

## Requisitos del sistema

- Python 3.8+
- FFmpeg instalado en el sistema
- Fuentes del sistema (DejaVu Sans Bold)

## Docker

El Dockerfile incluye todas las dependencias necesarias:
- Python 3.11
- FFmpeg
- Fuentes del sistema

## Licencia

MIT License
