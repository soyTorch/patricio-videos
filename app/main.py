import os
import tempfile
import subprocess
import shlex
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Response
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

def build_drawtext_expr(text: str, position: str) -> str:
    # Escapar ':' y '\' y "'" para drawtext
    safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    if position == "top":
        x_pos = "(w-text_w)/2"
        y_pos = "60"
    elif position == "center":
        x_pos = "(w-text_w)/2"
        y_pos = "(h-text_h)/2"
    else:  # bottom
        x_pos = "(w-text_w)/2"
        y_pos = "h-text_h-60"
    return f"drawtext=fontfile={FONT_PATH}:text='{safe}':fontsize=48:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=10:x={x_pos}:y={y_pos}"

def build_scale_pad(target: str) -> Optional[str]:
    if target in (None, "", "original"):
        return None
    if "x" in target:
        w, h = target.split("x", 1)
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    raise ValueError("Invalid target")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/render")
def render(
    authorization: Optional[str] = Header(None),
    video: UploadFile = File(...),
    audio: UploadFile = File(...),
    overlay_text: str = Form(""),
    position: str = Form("bottom"),
    mix_audio: str = Form("false"),
    target: str = Form("original"),
    crf: int = Form(18),
):
    check_auth(authorization)

    if position not in ("top", "center", "bottom"):
        return JSONResponse(status_code=400, content={"error": "position invalid"})
    try:
        crf = int(crf)
    except:
        return JSONResponse(status_code=400, content={"error": "crf invalid"})

    with tempfile.TemporaryDirectory() as tmp:
        vpath = os.path.join(tmp, "in_video.mp4")
        apath = os.path.join(tmp, "in_audio.mp3")
        taac  = os.path.join(tmp, "trim_audio.aac")
        out   = os.path.join(tmp, "out_final.mp4")

        # Guardar binarios
        with open(vpath, "wb") as f:
            f.write(video.file.read())
        with open(apath, "wb") as f:
            f.write(audio.file.read())

        # Duración vídeo
        dur = ffprobe_duration(vpath)
        dur_s = f"{dur:.3f}"

        # Recorte/normalización audio
        cmd_trim = f'ffmpeg -y -i "{apath}" -t {dur_s} -ac 2 -ar 48000 -c:a aac "{taac}"'
        run(cmd_trim)

        # Filtros de vídeo
        vf_parts = []
        scale = build_scale_pad(target)
        if scale:
            vf_parts.append(scale)
        vf_parts.append("format=yuv420p")
        vf_parts.append(build_drawtext_expr(overlay_text, position))
        vf = ",".join(vf_parts)

        # Audio: reemplazar o mezclar
        mix = (str(mix_audio).lower() == "true")
        if mix:
            # Mezcla audio original del vídeo + música recortada
            filter_complex = f'[0:a]volume=1.0[a0];[1:a]volume=0.35[a1];[a0][a1]amix=inputs=2:duration=shortest[aout];[0:v]{vf}[v]'
            cmd = (
                f'ffmpeg -y -i "{vpath}" -i "{taac}" -filter_complex "{filter_complex}" '
                f'-map "[v]" -map "[aout]" -c:v libx264 -preset veryfast -crf {crf} '
                f'-c:a aac -b:a 192k -shortest "{out}"'
            )
        else:
            # Reemplazo puro
            cmd = (
                f'ffmpeg -y -i "{vpath}" -i "{taac}" '
                f'-filter_complex "[0:v]{vf}[v]" -map "[v]" -map 1:a:0 '
                f'-c:v libx264 -preset veryfast -crf {crf} -c:a aac -b:a 192k '
                f'-shortest "{out}"'
            )

        try:
            run(cmd)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

        def iterfile():
            with open(out, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        headers = {"Content-Disposition": 'attachment; filename="out_final.mp4"'}
        return StreamingResponse(iterfile(), media_type="video/mp4", headers=headers)
