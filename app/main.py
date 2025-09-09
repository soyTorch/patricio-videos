import os
import tempfile
import subprocess
import shlex
import random
from typing import Optional
from PIL import Image, ImageDraw

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Response
import requests
from fastapi.responses import StreamingResponse, JSONResponse

API_KEY = os.getenv("API_KEY", "change_me")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

app = FastAPI(title="Video Render API", version="1.0.0")

def check_auth(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

def run(cmd: str):
    proc = subprocess.run(
        shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "ignore"))
    return proc.stdout.decode("utf-8", "ignore")

def ffprobe_duration(path: str) -> float:
    out = run(f'ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "{path}"')
    try:
        return float(out.strip())
    except:
        raise RuntimeError("Cannot read duration")

def get_random_audio_start(audio_path: str, video_duration: float) -> float:
    """Obtiene un punto de inicio aleatorio para el audio que permita cubrir toda la duración del video"""
    try:
        audio_duration = ffprobe_duration(audio_path)
        if audio_duration <= video_duration:
            return 0.0  # Si el audio es más corto que el video, empezar desde el inicio
        
        # Calcular el rango válido para el inicio aleatorio
        max_start = audio_duration - video_duration
        return random.uniform(0, max_start)
    except:
        return 0.0  # En caso de error, empezar desde el inicio

def build_drawtext_expr(text: str, position: str) -> str:
    # Limpiar texto de caracteres problemáticos y escapar para drawtext
    # Remover emojis y caracteres no-ASCII que pueden causar problemas
    import re
    clean_text = re.sub(r'[^\x00-\x7F]+', '', text)  # Solo ASCII
    safe = clean_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace('"', '\\"')
    
    if position == "top":
        x_pos = "(w-text_w)/2"
        y_pos = "40"  # Más arriba
    elif position == "center":
        x_pos = "(w-text_w)/2"
        y_pos = "(h-text_h)/2-100"  # Un poco más arriba del centro
    else:  # bottom
        x_pos = "(w-text_w)/2"
        y_pos = "h-text_h-200"  # Más arriba que antes
    return f"drawtext=fontfile={FONT_PATH}:text='{safe}':fontsize=48:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=10:x={x_pos}:y={y_pos}"

def build_image_overlay_filter(image_path: str) -> str:
    """Construye el filtro para superponer una imagen con bordes redondeados en el centro"""
    # Crear imagen con bordes redondeados y redimensionar
    return (
        f"[1:v]scale=400:400:force_original_aspect_ratio=decrease,"
        f"pad=400:400:(ow-iw)/2:(oh-ih)/2:color=white@0,"
        f"geq=lum='if(gt(abs(W/2-X),W/2-20)*gt(abs(H/2-Y),H/2-20)*"
        f"gt(hypot(20-(W/2-abs(W/2-X)),20-(H/2-abs(H/2-Y))),20),0,lum(X,Y))':"
        f"cb='if(gt(abs(W/2-X),W/2-20)*gt(abs(H/2-Y),H/2-20)*"
        f"gt(hypot(20-(W/2-abs(W/2-X)),20-(H/2-abs(H/2-Y))),20),128,cb(X,Y))':"
        f"cr='if(gt(abs(W/2-X),W/2-20)*gt(abs(H/2-Y),H/2-20)*"
        f"gt(hypot(20-(W/2-abs(W/2-X)),20-(H/2-abs(H/2-Y))),20),128,cr(X,Y))'[rounded]"
    )

def build_dark_overlay_filter(opacity: float) -> str:
    """Construye el filtro para añadir una capa oscura al video"""
    return f"color=black@{opacity}:size=1080x1920[overlay]"

def build_scale_pad(target: str) -> Optional[str]:
    if target in (None, "", "original"):
        return None
    if target == "vertical" or target == "9:16":
        # Formato vertical optimizado para redes sociales
        return "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    if "x" in target:
        w, h = target.split("x", 1)
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    raise ValueError("Invalid target")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/render")
def render(
    authorization: Optional[str] = Header(None),
    # Solo URLs (fuentes obligatorias)
    video_url: str = Form(...),
    audio_url: str = Form(...),
    overlay_image_url: str = Form(""),
    # Personalización
    overlay_text: str = Form(""),
    position: str = Form("bottom"),
    mix_audio: str = Form("false"),
    target: str = Form("original"),
    crf: int = Form(18),
    random_audio_start: str = Form("false"),
    dark_overlay: str = Form("false"),
    dark_overlay_opacity: float = Form(0.4),
    saturation_boost: float = Form(1.06),
):
    check_auth(authorization)

    if position not in ("top", "center", "bottom"):
        return JSONResponse(status_code=400, content={"error": "position invalid"})
    try:
        crf = int(crf)
    except:
        return JSONResponse(status_code=400, content={"error": "crf invalid"})

    # Validación: URLs obligatorias
    if not video_url:
        return JSONResponse(status_code=400, content={"error": "video_url required"})
    if not audio_url:
        return JSONResponse(status_code=400, content={"error": "audio_url required"})

    with tempfile.TemporaryDirectory() as tmp:
        vpath = os.path.join(tmp, "in_video.mp4")
        apath = os.path.join(tmp, "in_audio.mp3")
        taac  = os.path.join(tmp, "trim_audio.aac")
        # Prepara ruta de imagen si viene como archivo o URL
        ipath = os.path.join(tmp, "overlay_image.jpg") if overlay_image_url else None
        out   = os.path.join(tmp, "out_final.mp4")

        # Guardar binarios
        # Descargar video/audio desde URL
        r = requests.get(video_url, timeout=60, allow_redirects=True)
        r.raise_for_status()
        with open(vpath, "wb") as f:
            f.write(r.content)

        r = requests.get(audio_url, timeout=60, allow_redirects=True)
        r.raise_for_status()
        with open(apath, "wb") as f:
            f.write(r.content)
        
        # Guardar imagen si se proporciona
        if overlay_image_url:
            r = requests.get(overlay_image_url, timeout=60, allow_redirects=True)
            r.raise_for_status()
            with open(ipath, "wb") as f:
                f.write(r.content)
        
            # Preprocesar imagen: redondear 8px, escalar dentro de 400x400 y centrar sobre lienzo 400x400
            try:
                rounded_path = os.path.join(tmp, "overlay_image_rounded.png")
                with Image.open(ipath) as im:
                    im = im.convert("RGBA")
                    max_w, max_h = 400, 400
                    im.thumbnail((max_w, max_h))
                    w, h = im.size
                    radius = 24
                    mask = Image.new("L", (w, h), 0)
                    draw = ImageDraw.Draw(mask)
                    draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
                    im.putalpha(mask)
                    canvas = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
                    canvas.paste(im, ((max_w - w) // 2, (max_h - h) // 2), im)
                    canvas.save(rounded_path)
                ipath = rounded_path
            except Exception:
                # Si Pillow falla, continuar con la imagen original
                pass

        # Duración vídeo
        dur = ffprobe_duration(vpath)
        dur_s = f"{dur:.3f}"

        # Obtener punto de inicio aleatorio del audio si se solicita
        audio_start = 0.0
        if str(random_audio_start).lower() == "true":
            audio_start = get_random_audio_start(apath, dur)
            print(f"DEBUG: Using random audio start at {audio_start:.3f} seconds")

        # Recorte/normalización audio con punto de inicio aleatorio
        cmd_trim = f'ffmpeg -y -ss {audio_start:.3f} -i "{apath}" -t {dur_s} -ac 2 -ar 48000 -c:a aac "{taac}"'
        run(cmd_trim)

        # Construir comando FFmpeg - versión simplificada pero funcional
        
        # Con imagen - construir grafo con labels explícitas y sin filtros vacíos
        if ipath:
            inputs_cmd = f'-i "{vpath}" -i "{taac}" -i "{ipath}"'

            # Preparar fragmentos de filtro de forma determinista
            parts = []

            # 1) La imagen ya está procesada (PNG con alpha). Solo asegurar formato rgba
            parts.append("[2:v]format=rgba[img]")

            # 2) Preparar el video base: si hay escala/pad, aplicarlo; si no, usar 'null'
            scale = build_scale_pad(target)
            if scale:
                parts.append(f"[0:v]{scale},eq=saturation={saturation_boost}[base]")
            else:
                parts.append(f"[0:v]eq=saturation={saturation_boost}[base]")

            # 3) Si se solicita, aplicar una capa oscura sobre el video base
            base_label = "base"
            if str(dark_overlay).lower() == "true":
                parts.append(f"color=black@{dark_overlay_opacity}:size=1080x1920[dark]")
                parts.append("[base][dark]overlay[base_dark]")
                base_label = "base_dark"

            # 4) Hacer overlay de la imagen centrada
            parts.append(f"[{base_label}][img]overlay=(W-w)/2:(H-h)/2[ov]")

            # 5) Añadir texto si corresponde
            if overlay_text:
                text_filter = build_drawtext_expr(overlay_text, position)
                # Encadena drawtext correctamente sobre la etiqueta previa
                parts.append(f"[ov]{text_filter}[ov2]")
                final_in = "[ov2]"
            else:
                final_in = "[ov]"

            # 6) Formato final y label de salida (sin coma tras la etiqueta)
            parts.append(f"{final_in}format=yuv420p[v]")

            filter_parts = [';'.join(parts)]
            
        else:
            # Sin imagen - aplicar escala, capa oscura opcional y texto con labels explícitas
            inputs_cmd = f'-i "{vpath}" -i "{taac}"'

            parts = []
            scale = build_scale_pad(target)
            if scale:
                parts.append(f"[0:v]{scale},eq=saturation={saturation_boost}[base]")
            else:
                parts.append(f"[0:v]eq=saturation={saturation_boost}[base]")

            base_label = "base"
            if str(dark_overlay).lower() == "true":
                parts.append(f"color=black@{dark_overlay_opacity}:size=1080x1920[dark]")
                parts.append("[base][dark]overlay[base_dark]")
                base_label = "base_dark"

            final_in = f"[{base_label}]"
            if overlay_text:
                text_filter = build_drawtext_expr(overlay_text, position)
                parts.append(f"{final_in}{text_filter}[txt]")
                final_in = "[txt]"

            parts.append(f"{final_in}format=yuv420p[v]")
            filter_parts = [';'.join(parts)]
        
        # Audio
        mix = (str(mix_audio).lower() == "true")
        if mix:
            filter_parts.append("[0:a]volume=1.0[a0];[1:a]volume=0.35[a1];[a0][a1]amix=inputs=2:duration=shortest[aout]")
            audio_map = "[aout]"
        else:
            audio_map = "1:a:0"
        
        # Comando final
        filter_complex = ";".join(filter_parts)
        cmd = (
            f'ffmpeg -y {inputs_cmd} -filter_complex "{filter_complex}" '
            f'-map "[v]" -map {audio_map} -c:v libx264 -preset veryfast -crf {crf} '
            f'-c:a aac -b:a 192k -shortest "{out}"'
        )

        try:
            print(f"DEBUG: Executing FFmpeg command: {cmd}")
            run(cmd)
            print(f"DEBUG: FFmpeg completed successfully")
        except Exception as e:
            print(f"DEBUG: FFmpeg failed with error: {str(e)}")
            return JSONResponse(status_code=500, content={"error": f"FFmpeg error: {str(e)}"})

        # Verificar que el archivo se creó
        if not os.path.exists(out):
            print(f"DEBUG: Output file does not exist: {out}")
            return JSONResponse(status_code=500, content={"error": "Video processing failed - output file not created"})
        
        file_size = os.path.getsize(out)
        print(f"DEBUG: Output file created successfully, size: {file_size} bytes")
        
        if file_size == 0:
            return JSONResponse(status_code=500, content={"error": "Video processing failed - output file is empty"})

        # Leer el archivo completo antes de que se elimine el directorio temporal
        print(f"DEBUG: Reading output file into memory")
        with open(out, "rb") as f:
            video_data = f.read()
        print(f"DEBUG: File read successfully, {len(video_data)} bytes in memory")

    # Ahora el directorio temporal se ha eliminado, pero tenemos los datos en memoria
    def iterfile():
        # Convertir bytes a chunks para streaming
        chunk_size = 1024 * 1024  # 1MB chunks
        for i in range(0, len(video_data), chunk_size):
            yield video_data[i:i + chunk_size]

    headers = {"Content-Disposition": 'attachment; filename="out_final.mp4"'}
    return StreamingResponse(iterfile(), media_type="video/mp4", headers=headers)
