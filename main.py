import base64
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR.parent

app = FastAPI(title="HAIDARA AI")

static_dir = APP_DIR / "static"
if not static_dir.exists():
    static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

MODELS_TO_TRY = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

SYSTEM_INSTRUCTION = (
    "Tu es HAIDARA AI, un assistant intelligent de haut niveau. "
    "Réponds toujours en français (sauf demande contraire) de façon claire, complète, "
    "structurée et détaillée comme Gemini : utilise des titres clairs, des listes à puces, "
    "du gras sur les notions clés et des exemples concrets quand c'est utile."
)


class ChatRequest(BaseModel):
    message: str


class ImageRequest(BaseModel):
    prompt: str


def find_index_html() -> Optional[Path]:
    candidates = [
        BASE_DIR / "templates" / "index.html",
        BASE_DIR / "static" / "index.html",
        BASE_DIR / "index.html",
        APP_DIR / "templates" / "index.html",
        APP_DIR / "static" / "index.html",
        APP_DIR / "index.html",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def extract_reply_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    parts_out: list[str] = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                parts_out.append(part_text.strip())
    if parts_out:
        return "\n".join(parts_out)

    return "Aucune réponse textuelle reçue du modèle."


def get_genai_client() -> tuple[Any, Optional[str]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, (
            "Clé `GEMINI_API_KEY` non détectée dans cette fenêtre CMD. "
            "Tape `set GEMINI_API_KEY=TA_CLE_API` avant de lancer Uvicorn."
        )
    if genai is None:
        return None, "Le paquet `google-genai` n'est pas installé dans l'environnement."
    return genai.Client(api_key=api_key), None


def discover_available_flash_models(client: Any) -> list[str]:
    discovered: list[str] = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            short_name = name.replace("models/", "")
            methods = getattr(m, "supported_generation_methods", None) or getattr(m, "supported_actions", None) or []
            if "flash" in short_name.lower() and (not methods or "generateContent" in methods):
                discovered.append(short_name)
    except Exception:
        pass
    return discovered


def call_gemini(contents: Any, max_attempts: int = 2) -> str:
    client, err = get_genai_client()
    if err:
        return err

    candidates_models = list(MODELS_TO_TRY)
    for m in discover_available_flash_models(client):
        if m not in candidates_models:
            candidates_models.append(m)

    last_err = ""
    for model_name in candidates_models:
        for attempt in range(max_attempts):
            try:
                config = (
                    types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
                    if types is not None
                    else None
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                return extract_reply_text(response)
            except Exception as exc:
                last_err = str(exc)
                if ("503" in last_err or "UNAVAILABLE" in last_err) and attempt < max_attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if "404" in last_err or "NOT_FOUND" in last_err:
                    break
                return f"Erreur Gemini ({model_name}) : {last_err}"

    return f"Impossible d'obtenir une réponse : {last_err}"


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    index_path = find_index_html()
    if index_path is not None:
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>HAIDARA AI</h1><p>Fichier index.html introuvable.</p>",
        status_code=200,
    )


@app.post("/chat")
async def chat_endpoint(request: Request, payload: Optional[ChatRequest] = None) -> JSONResponse:
    user_message = ""
    if payload and payload.message:
        user_message = payload.message.strip()
    else:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                user_message = str(raw.get("message") or raw.get("prompt") or "").strip()
        except Exception:
            pass

    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"reply": "Écris un message avant d'envoyer."},
        )

    reply = call_gemini(user_message)
    return JSONResponse(content={"reply": reply})


@app.post("/upload")
async def upload_endpoint(request: Request) -> JSONResponse:
    client, err = get_genai_client()
    if err:
        return JSONResponse(content={"reply": err})

    try:
        form = await request.form()
    except Exception as exc:
        return JSONResponse(
            content={"reply": f"Erreur de lecture du formulaire : {exc}"}
        )

    uploaded = form.get("file")
    message = str(form.get("message") or "").strip()

    if not isinstance(uploaded, UploadFile):
        return JSONResponse(content={"reply": "Aucun fichier reçu."})

    raw_bytes = await uploaded.read()
    if not raw_bytes:
        return JSONResponse(content={"reply": "Le fichier est vide."})

    filename = uploaded.filename or "fichier"
    content_type = uploaded.content_type or "application/octet-stream"
    prompt_text = message or f"Analyse ce fichier ({filename}) et explique son contenu en détail."

    try:
        if (content_type.startswith("image/") or content_type == "application/pdf") and types is not None:
            part = types.Part.from_bytes(data=raw_bytes, mime_type=content_type)
            reply = call_gemini([part, prompt_text])
            return JSONResponse(content={"reply": reply})

        decoded = raw_bytes.decode("utf-8", errors="replace")[:15000]
        reply = call_gemini(f"{prompt_text}\n\nContenu de `{filename}` :\n```\n{decoded}\n```")
        return JSONResponse(content={"reply": reply})
    except Exception as exc:
        return JSONResponse(content={"reply": f"Erreur lors de l'analyse du fichier : {exc}"})


@app.post("/generate-image")
async def generate_image_endpoint(payload: ImageRequest) -> JSONResponse:
    prompt = payload.prompt.strip()
    if not prompt:
        return JSONResponse(content={"error": "Décris l'image à créer."})

    client, err = get_genai_client()
    if err:
        return JSONResponse(content={"error": err})

    last_err = ""
    try:
        res = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1) if types is not None else None,
        )
        generated = getattr(res, "generated_images", None) or []
        if generated:
            img_bytes = generated[0].image.image_bytes
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return JSONResponse(content={"image_url": f"data:image/png;base64,{b64}"})
    except Exception as exc:
        last_err = str(exc)

    try:
        res = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]) if types is not None else None,
        )
        for cand in getattr(res, "candidates", None) or []:
            for part in getattr(getattr(cand, "content", None), "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    mime = getattr(inline, "mime_type", "image/png")
                    raw_data = inline.data
                    b64 = base64.b64encode(raw_data).decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data)
                    return JSONResponse(content={"image_url": f"data:{mime};base64,{b64}"})
    except Exception as exc:
        last_err = str(exc)

    return JSONResponse(
        content={"error": f"Création d'image indisponible sur ce compte/modèle ({last_err})."}
    )
