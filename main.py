import os
import json
import uuid
import base64
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pypdf import PdfReader
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PAYMENTS_FILE = DATA_DIR / "payments.json"

app = FastAPI(title="HAIDARA AI")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

TEXT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

IMAGE_MODELS = [
    "imagen-3.0-generate-002",
    "gemini-2.5-flash-image",
]


def get_api_keys() -> List[str]:
    names = [
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_2",
        "GEMINI_API_KEY_3",
        "GEMINI_API_KEY_4",
        "GEMINI_API_KEY_5",
    ]
    keys = []
    for name in names:
        val = os.getenv(name, "").strip().strip('"').strip("'")
        if val and val not in keys:
            keys.append(val)
    return keys


def load_payments() -> List[Dict[str, Any]]:
    if not PAYMENTS_FILE.exists():
        return []
    try:
        return json.loads(PAYMENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_payments(items: List[Dict[str, Any]]) -> None:
    PAYMENTS_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages):
        txt = (page.extract_text() or "").strip()
        if txt:
            parts.append(f"[Page {i + 1}]\n{txt}")
    return "\n\n".join(parts)


async def build_contents(prompt: str, files: List[UploadFile]) -> List[Any]:
    contents: List[Any] = []
    text_notes: List[str] = []

    for f in files or []:
        raw = await f.read()
        if not raw:
            continue
        mime = (f.content_type or "").lower()
        filename = f.filename or "fichier"

        if mime.startswith("image/"):
            contents.append(
                types.Part.from_bytes(
                    data=raw,
                    mime_type=mime,
                )
            )
        elif mime == "application/pdf" or filename.lower().endswith(".pdf"):
            extracted = extract_text_from_pdf(raw)
            if extracted:
                text_notes.append(f"--- Contenu PDF ({filename}) ---\n{extracted[:12000]}")
            else:
                contents.append(
                    types.Part.from_bytes(
                        data=raw,
                        mime_type="application/pdf",
                    )
                )
        else:
            decoded = raw.decode("utf-8", errors="ignore").strip()
            if decoded:
                text_notes.append(f"--- Fichier ({filename}) ---\n{decoded[:12000]}")

    full_prompt = prompt.strip() if prompt else "Analyse les éléments fournis."
    if text_notes:
        full_prompt = f"{full_prompt}\n\n" + "\n\n".join(text_notes)

    contents.append(full_prompt)
    return contents


def generate_with_failover(contents: List[Any]) -> Dict[str, Any]:
    api_keys = get_api_keys()
    if not api_keys:
        raise RuntimeError("Aucune clé GEMINI_API_KEY configurée sur Render.")

    last_error = "Erreur inconnue"
    for key in api_keys:
        client = genai.Client(api_key=key)
        for model in TEXT_MODELS:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                )
                reply = (resp.text or "").strip()
                if reply:
                    return {"reply": reply, "model": model}
            except Exception as exc:
                last_error = str(exc)
                continue

    raise RuntimeError(f"Toutes les clés ou modèles ont échoué : {last_error}")


def generate_image_with_failover(prompt: str) -> Dict[str, Any]:
    api_keys = get_api_keys()
    if not api_keys:
        raise RuntimeError("Aucune clé GEMINI_API_KEY configurée sur Render.")

    last_error = "Erreur génération image"
    for key in api_keys:
        client = genai.Client(api_key=key)
        for model in IMAGE_MODELS:
            try:
                if model.startswith("imagen"):
                    res = client.models.generate_images(
                        model=model,
                        prompt=prompt,
                        config=types.GenerateImagesConfig(
                            number_of_images=1,
                            output_mime_type="image/png",
                        ),
                    )
                    if res.generated_images:
                        img_bytes = res.generated_images[0].image.image_bytes
                        b64 = base64.b64encode(img_bytes).decode("utf-8")
                        return {
                            "image_base64": b64,
                            "mime_type": "image/png",
                            "model": model,
                        }
                else:
                    res = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"],
                        ),
                    )
                    for cand in getattr(res, "candidates", []) or []:
                        content = getattr(cand, "content", None)
                        for part in getattr(content, "parts", []) or []:
                            inline = getattr(part, "inline_data", None)
                            if inline and getattr(inline, "data", None):
                                raw_data = inline.data
                                if isinstance(raw_data, bytes):
                                    b64 = base64.b64encode(raw_data).decode("utf-8")
                                else:
                                    b64 = raw_data
                                return {
                                    "image_base64": b64,
                                    "mime_type": getattr(inline, "mime_type", "image/png"),
                                    "model": model,
                                }
            except Exception as exc:
                last_error = str(exc)
                continue

    raise RuntimeError(f"Génération d'image impossible : {last_error}")


class PaymentSubmit(BaseModel):
    phone: str
    amount: str
    reference: str
    plan: Optional[str] = "Standard"


class AdminAction(BaseModel):
    password: str
    payment_id: Optional[str] = None
    status: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "keys_configured": len(get_api_keys())}


@app.post("/api/chat")
async def api_chat(
    message: str = Form(""),
    files: List[UploadFile] = File(default=[]),
):
    try:
        contents = await build_contents(message, files)
        result = generate_with_failover(contents)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/generate-image")
async def api_generate_image(prompt: str = Form(...)):
    try:
        result = generate_image_with_failover(prompt)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/payments/submit")
async def submit_payment(payload: PaymentSubmit):
    payments = load_payments()
    record = {
        "id": str(uuid.uuid4())[:8],
        "phone": payload.phone.strip(),
        "amount": payload.amount.strip(),
        "reference": payload.reference.strip(),
        "plan": (payload.plan or "Standard").strip(),
        "status": "pending",
    }
    payments.insert(0, record)
    save_payments(payments)
    return {"ok": True, "payment": record}


@app.post("/api/admin/payments")
async def list_payments(payload: AdminAction):
    if payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Mot de passe admin incorrect.")
    return {"ok": True, "payments": load_payments()}


@app.post("/api/admin/payments/update")
async def update_payment(payload: AdminAction):
    if payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Mot de passe admin incorrect.")
    if not payload.payment_id or payload.status not in {"approved", "rejected", "pending"}:
        raise HTTPException(status_code=400, detail="Données de mise à jour invalides.")

    payments = load_payments()
    for p in payments:
        if p["id"] == payload.payment_id:
            p["status"] = payload.status
            save_payments(payments)
            return {"ok": True, "payment": p}

    raise HTTPException(status_code=404, detail="Paiement introuvable.")
