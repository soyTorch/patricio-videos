import os
import tempfile
import subprocess
import shlex
import random
from typing import Optional
from PIL import Image, ImageDraw

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Response
import requests
import re
from fastapi.responses import StreamingResponse, JSONResponse
from google.oauth2.service_account import Credentials as GCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import glob

API_KEY = os.getenv("API_KEY", "change_me")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

app = FastAPI(title="Video Render API", version="1.0.0")

# Init Google Drive credentials if provided inline in env
def _init_inline_service_account_from_env():
    try:
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            inline_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
            inline_json_b64 = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON_B64")
            if inline_json_b64 and not inline_json:
                import base64
                try:
                    inline_json = base64.b64decode(inline_json_b64).decode("utf-8")
                except Exception as e:
                    print(f"DEBUG: Could not decode GDRIVE_SERVICE_ACCOUNT_JSON_B64: {e}")
                    inline_json = None
            if inline_json:
                out_path = "/tmp/gdrive_sa.json"
                with open(out_path, "w") as f:
                    f.write(inline_json)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = out_path
                print("DEBUG: Wrote inline service account to /tmp and set GOOGLE_APPLICATION_CREDENTIALS")
    except Exception as e:
        print(f"DEBUG: Unable to init inline service account: {e}")

_init_inline_service_account_from_env()

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

def _to_direct_drive_url(url: str) -> str:
    if "drive.google.com" not in url:
        return url
    
    # Extraer ID del archivo de diferentes formatos de URL de Google Drive
    file_id = None
    
    # Formato: /file/d/<ID>/view o /file/d/<ID>/
    m = re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
    if m:
        file_id = m.group(1)
    
    # Formato: id=<ID>
    if not file_id:
        m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
        if m:
            file_id = m.group(1)
    
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    
    return url

def _download_with_drive_confirm(url: str, out_path: str) -> None:
    """Mejorada función de descarga para Google Drive con mejor manejo de confirmación"""
    url = _to_direct_drive_url(url)
    print(f"DEBUG: Downloading from URL: {url}")
    
    session = requests.Session()
    
    # Headers para simular un navegador
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Intentar primero con la API oficial si hay credenciales y file_id
        file_id_match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
        file_id_api = file_id_match.group(1) if file_id_match else None
        service = _maybe_get_drive_service()
        if service and file_id_api:
            print("DEBUG: Trying Google Drive API download")
            _download_via_drive_api(service, file_id_api, out_path)
            print("DEBUG: Google Drive API download completed")
            if os.path.getsize(out_path) > 0:
                return

        # Primera petición
        resp = session.get(url, headers=headers, timeout=90, allow_redirects=True, stream=True)
        print(f"DEBUG: First response status: {resp.status_code}")
        print(f"DEBUG: Content-Type: {resp.headers.get('Content-Type', 'N/A')}")
        
        # Verificar si es HTML (página de confirmación de Google Drive)
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            print("DEBUG: Received HTML response, looking for confirmation token")
            
            # Leer el contenido HTML
            html_content = ""
            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                if chunk:
                    html_content += chunk
                # Limitar la lectura para evitar descargar todo el HTML
                if len(html_content) > 100000:  # 100KB debería ser suficiente
                    break
            
            # Buscar token de confirmación y UUID
            confirm_match = re.search(r'name="confirm"\s+value="([^"]+)"', html_content)
            uuid_match = re.search(r'name="uuid"\s+value="([^"]+)"', html_content)
            
            if confirm_match:
                confirm_token = confirm_match.group(1)
                print(f"DEBUG: Found confirm token: {confirm_token}")
                
                # Extraer ID del archivo de la URL original
                file_id_match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
                if file_id_match:
                    file_id = file_id_match.group(1)
                    
                    # Construir URL con token de confirmación
                    confirm_url = f"https://drive.google.com/uc?export=download&confirm={confirm_token}&id={file_id}"
                    if uuid_match:
                        uuid_token = uuid_match.group(1)
                        confirm_url += f"&uuid={uuid_token}"
                    
                    print(f"DEBUG: Using confirmation URL: {confirm_url}")
                    
                    # Segunda petición con confirmación
                    resp = session.get(confirm_url, headers=headers, timeout=120, allow_redirects=True, stream=True)
                    print(f"DEBUG: Confirmation response status: {resp.status_code}")
                    print(f"DEBUG: Confirmation Content-Type: {resp.headers.get('Content-Type', 'N/A')}")
                else:
                    print("DEBUG: Could not extract file ID for confirmation")
            else:
                print("DEBUG: No confirmation token found in HTML")
                # Intentar buscar un enlace de descarga directo en el HTML
                download_link_match = re.search(r'href="(https://drive\.google\.com/uc\?[^"]*export=download[^"]*)"', html_content)
                if download_link_match:
                    direct_url = download_link_match.group(1).replace('&amp;', '&')
                    print(f"DEBUG: Found direct download link: {direct_url}")
                    resp = session.get(direct_url, headers=headers, timeout=120, allow_redirects=True, stream=True)
                    print(f"DEBUG: Direct download response status: {resp.status_code}")
        
        # Verificar que tenemos una respuesta válida
        resp.raise_for_status()
        
        # Verificar el Content-Type final
        final_content_type = resp.headers.get("Content-Type", "").lower()
        print(f"DEBUG: Final Content-Type: {final_content_type}")
        
        if "text/html" in final_content_type:
            print("WARNING: Still receiving HTML - download may have failed")
            # Intentar leer un poco del contenido para verificar
            peek = next(resp.iter_content(chunk_size=1024), b"")
            if b"<!DOCTYPE html" in peek or b"<html" in peek:
                raise RuntimeError("Download failed - received HTML instead of file content")
        
        # Descargar el archivo
        print(f"DEBUG: Starting file download to: {out_path}")
        total_size = 0
        
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
        
        print(f"DEBUG: Downloaded {total_size} bytes")
        
        # Verificar que el archivo se descargó correctamente
        if total_size == 0:
            raise RuntimeError("Downloaded file is empty")
        
        # Verificar que el archivo existe y tiene contenido
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("Download failed - file is empty or doesn't exist")
            
        print(f"DEBUG: File downloaded successfully, size: {os.path.getsize(out_path)} bytes")
        
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Request failed: {str(e)}")
        raise RuntimeError(f"Failed to download file: {str(e)}")
    except Exception as e:
        print(f"DEBUG: Unexpected error during download: {str(e)}")
        raise RuntimeError(f"Download error: {str(e)}")

def _maybe_get_drive_service():
    try:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        # Fallback: usar credencial local en el repo (p.ej. video-generator-*.json)
        if not creds_path or not os.path.exists(creds_path):
            cwd = os.getcwd()
            # Intenta nombre explícito primero
            explicit = os.path.join(cwd, "video-generator-471617-b782bb619dcc.json")
            candidates = [explicit] + glob.glob(os.path.join(cwd, "video-generator-*-*.json"))
            for cand in candidates:
                if os.path.exists(cand):
                    creds_path = cand
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
                    print(f"DEBUG: Using local Drive credentials: {creds_path}")
                    break
        if not creds_path or not os.path.exists(creds_path):
            return None
        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        creds = GCredentials.from_service_account_file(creds_path, scopes=scopes)
        # cache_discovery=False evita escribir en disco en entornos limitados
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"DEBUG: Could not init Drive service: {e}")
        return None

def _download_via_drive_api(service, file_id: str, out_path: str):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(out_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"DEBUG: Drive API download {int(status.progress() * 100)}%")

def ffprobe_duration(path: str) -> float:
    """Obtener duración del archivo con mejor manejo de errores"""
    print(f"DEBUG: Getting duration for: {path}")
    
    # Verificar que el archivo existe y no está vacío
    if not os.path.exists(path):
        raise RuntimeError(f"File does not exist: {path}")
    
    file_size = os.path.getsize(path)
    if file_size == 0:
        raise RuntimeError(f"File is empty: {path}")
    
    print(f"DEBUG: File size: {file_size} bytes")
    
    try:
        # Intentar obtener información básica del archivo primero
        probe_cmd = f'ffprobe -v quiet -print_format json -show_format "{path}"'
        out = run(probe_cmd)
        print(f"DEBUG: ffprobe output: {out[:200]}...")
        
        # Luego obtener la duración
        out = run(f'ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "{path}"')
        duration = float(out.strip())
        print(f"DEBUG: Duration: {duration} seconds")
        return duration
    except ValueError as e:
        print(f"DEBUG: Could not parse duration: {out.strip()}")
        raise RuntimeError(f"Cannot parse duration from: {out.strip()}")
    except Exception as e:
        print(f"DEBUG: ffprobe failed: {str(e)}")
        # Intentar con más verbosidad para diagnosticar el problema
        try:
            debug_out = run(f'ffprobe -v debug "{path}"')
            print(f"DEBUG: ffprobe debug output: {debug_out[:500]}...")
        except:
            pass
        raise RuntimeError(f"Cannot read file duration. File may be corrupted: {str(e)}")

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

        try:
            # Descargar archivos
            print(f"DEBUG: Starting download of video from: {video_url}")
            _download_with_drive_confirm(video_url, vpath)
            print(f"DEBUG: Video download completed")
            
            print(f"DEBUG: Starting download of audio from: {audio_url}")
            _download_with_drive_confirm(audio_url, apath)
            print(f"DEBUG: Audio download completed")
            
            # Guardar imagen si se proporciona
            if overlay_image_url:
                print(f"DEBUG: Starting download of image from: {overlay_image_url}")
                _download_with_drive_confirm(overlay_image_url, ipath)
                print(f"DEBUG: Image download completed")
            
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
                    print(f"DEBUG: Image preprocessing completed")
                except Exception as e:
                    print(f"DEBUG: Image preprocessing failed: {str(e)}")
                    # Si Pillow falla, continuar con la imagen original
                    pass

        except Exception as e:
            print(f"DEBUG: Download failed: {str(e)}")
            return JSONResponse(status_code=500, content={"error": f"Download failed: {str(e)}"})

        # Verificar archivos descargados
        if not os.path.exists(vpath) or os.path.getsize(vpath) == 0:
            return JSONResponse(status_code=500, content={"error": "Video download failed or file is empty"})
        if not os.path.exists(apath) or os.path.getsize(apath) == 0:
            return JSONResponse(status_code=500, content={"error": "Audio download failed or file is empty"})

        # Duración vídeo
        try:
            dur = ffprobe_duration(vpath)
            dur_s = f"{dur:.3f}"
            print(f"DEBUG: Video duration: {dur} seconds")
        except Exception as e:
            print(f"DEBUG: Failed to get video duration: {str(e)}")
            return JSONResponse(status_code=500, content={"error": f"Cannot process video file: {str(e)}"})

        # Obtener punto de inicio aleatorio del audio si se solicita
        audio_start = 0.0
        if str(random_audio_start).lower() == "true":
            audio_start = get_random_audio_start(apath, dur)
            print(f"DEBUG: Using random audio start at {audio_start:.3f} seconds")

        # Recorte/normalización audio con punto de inicio aleatorio
        try:
            cmd_trim = f'ffmpeg -y -ss {audio_start:.3f} -i "{apath}" -t {dur_s} -ac 2 -ar 48000 -c:a aac "{taac}"'
            print(f"DEBUG: Trimming audio with command: {cmd_trim}")
            run(cmd_trim)
            print(f"DEBUG: Audio trimming completed")
        except Exception as e:
            print(f"DEBUG: Audio trimming failed: {str(e)}")
            return JSONResponse(status_code=500, content={"error": f"Audio processing failed: {str(e)}"})

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