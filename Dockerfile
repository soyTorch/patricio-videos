# Usar imagen oficial de Python
FROM python:3.11-slim

# Configurar variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar dependencias del sistema para FFmpeg y herramientas
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar requirements y instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY app/ ./app/

# (Opcional) Copiar credencial de Google Drive si está presente en el repo
# y definirla como predeterminada dentro del contenedor
COPY video-generator-471617-b782bb619dcc.json /app/video-generator-471617-b782bb619dcc.json
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/video-generator-471617-b782bb619dcc.json

# Crear directorio para archivos temporales
RUN mkdir -p temp_videos

# Variables de entorno
ENV HOST=0.0.0.0 
ENV PORT=8023 
ENV API_KEY=change_me 
ENV GENERIC_TIMEZONE=Europe/Madrid

# Exponer puerto
EXPOSE 8023

# Comando para ejecutar la aplicación
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8023"]
