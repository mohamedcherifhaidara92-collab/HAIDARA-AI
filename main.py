"""
HAIDARA AI - Backend FastAPI
Interface blanche style Grok + Gemini 3.8 Flash + crédits Orange Money
"""

import os
import uuid
import sqlite3
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from fastapi import FastAPI, Request, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import google.generativeai as genai

# ==================== CONFIG ====================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "haidara2026")  # Change-le !
ORANGE_MONEY_NUMBER = "+224629600906"
FREE_MESSAGES = 10
DATABASE_PATH = os.getenv("DATABASE_PATH", "haidara.db")

# Packs disponibles
PACKS = {
    "standard": {
        "name": "Standard",
        "price": 20000,
        "messages": 50,
        "premium": False,
        "label": "50 messages"
    },
    "premium": {
        "name": "Premium",
        "price": 50000,
        "messages": 200,
        "premium": True,
        "label": "200 messages + Premium"
    },
}

# ==================== INIT ====================
app = FastAPI(title="HAIDARA AI", version="2.0.0")
templates = Jinja2Templates(directory="templates")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==================== DATABASE ====================
def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                free_used INTEGER DEFAULT 0,
                credits INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                created_at TEXT,
                last_seen TEXT
            )
        """)
        # Migration douce si la colonne n'existe pas encore
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                reference TEXT UNIQUE,
                pack_type TEXT DEFAULT 'standard',
                amount INTEGER,
                messages INTEGER,
                transaction_id TEXT,
                status TEXT DEFAULT 'pending',  -- pending / approved / rejected
                created_at TEXT,
                approved_at TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN pack_type TEXT DEFAULT 'standard'")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

init_db()

# ==================== MODELS ====================
class ChatRequest(BaseModel):
    message: str
    user_id: str
    history: Optional[List[Dict[str, str]]] = None

class RedeemRequest(BaseModel):
    user_id: str
    transaction_id: str
    reference: str

class AdminApprove(BaseModel):
    payment_id: int
    password: str

# ==================== HELPERS ====================
def get_or_create_user(user_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        now = datetime.utcnow().isoformat()
        if row:
            conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user_id))
            conn.commit()
            d = dict(row)
            if "is_premium" not in d:
                d["is_premium"] = 0
            return d
        conn.execute(
            "INSERT INTO users (user_id, free_used, credits, is_premium, created_at, last_seen) VALUES (?, 0, 0, 0, ?, ?)",
            (user_id, now, now)
        )
        conn.commit()
        return {"user_id": user_id, "free_used": 0, "credits": 0, "is_premium": 0}

def can_chat(user: dict) -> tuple[bool, str]:
    free_left = max(0, FREE_MESSAGES - user["free_used"])
    if free_left > 0:
        return True, f"free:{free_left}"
    if user["credits"] > 0:
        return True, f"credit:{user['credits']}"
    return False, "no_credits"

def consume_message(user_id: str):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            return
        free_used = user["free_used"]
        credits = user["credits"]
        if free_used < FREE_MESSAGES:
            conn.execute("UPDATE users SET free_used = free_used + 1 WHERE user_id = ?", (user_id,))
        elif credits > 0:
            conn.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def call_gemini(message: str, history: Optional[List[Dict]] = None) -> str:
    if not GEMINI_API_KEY:
        return "⚠️ Clé API Gemini manquante. Configure la variable d'environnement GEMINI_API_KEY."

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=(
                "Tu es HAIDARA AI, un assistant intelligent, poli, clair et utile. "
                "Tu réponds en français par défaut, sauf si l'utilisateur écrit dans une autre langue. "
                "Sois concis mais complet. Utilise un style moderne et agréable."
            )
        )

        # Build history for multi-turn
        chat_history = []
        if history:
            for h in history[-10:]:  # last 10 messages max
                role = "user" if h.get("role") == "user" else "model"
                chat_history.append({"role": role, "parts": [h.get("content", "")]})

        if chat_history:
            chat = model.start_chat(history=chat_history)
            response = chat.send_message(message)
        else:
            response = model.generate_content(message)

        return response.text or "Désolé, je n'ai pas pu générer de réponse."

    except Exception as e:
        err = str(e)
        if "API_KEY" in err.upper() or "401" in err or "403" in err:
            return "⚠️ Problème avec la clé API Gemini. Vérifie qu'elle est valide et active."
        if "quota" in err.lower() or "rate" in err.lower():
            return "⚠️ Quota Gemini dépassé temporairement. Réessaie dans quelques minutes."
        return f"⚠️ Erreur Gemini : {err[:200]}"

# ==================== ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "orange_number": ORANGE_MONEY_NUMBER,
        "free_messages": FREE_MESSAGES,
        "packs": PACKS,
    })

@app.get("/api/status")
async def status(user_id: str):
    user = get_or_create_user(user_id)
    free_left = max(0, FREE_MESSAGES - user["free_used"])
    return {
        "user_id": user_id,
        "free_left": free_left,
        "credits": user["credits"],
        "is_premium": bool(user.get("is_premium")),
        "can_chat": free_left > 0 or user["credits"] > 0,
        "orange_number": ORANGE_MONEY_NUMBER,
        "packs": PACKS,
    }

@app.post("/chat")
async def chat(payload: ChatRequest):
    user = get_or_create_user(payload.user_id)
    allowed, reason = can_chat(user)

    if not allowed:
        return JSONResponse({
            "error": "no_credits",
            "message": "Tu as utilisé tes 10 messages gratuits. Achète un pack pour continuer.",
            "free_left": 0,
            "credits": 0
        }, status_code=402)

    # Call Gemini
    reply = call_gemini(payload.message, payload.history)

    # Consume only if success (not error message starting with ⚠️)
    if not reply.startswith("⚠️"):
        consume_message(payload.user_id)

    # Refresh status
    user = get_or_create_user(payload.user_id)
    free_left = max(0, FREE_MESSAGES - user["free_used"])

    return {
        "reply": reply,
        "free_left": free_left,
        "credits": user["credits"],
    }

@app.post("/api/create-payment")
async def create_payment(user_id: str = Form(...), pack_type: str = Form("standard")):
    if pack_type not in PACKS:
        raise HTTPException(400, "Pack invalide")

    pack = PACKS[pack_type]
    user = get_or_create_user(user_id)
    reference = f"HAIDARA-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO payments (user_id, reference, pack_type, amount, messages, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, reference, pack_type, pack["price"], pack["messages"], now)
        )
        conn.commit()

    return {
        "reference": reference,
        "pack_type": pack_type,
        "pack_name": pack["name"],
        "amount": pack["price"],
        "messages": pack["messages"],
        "is_premium": pack["premium"],
        "orange_number": ORANGE_MONEY_NUMBER,
        "instructions": (
            f"1. Ouvre Orange Money\n"
            f"2. Envoie {pack['price']:,} GNF au numéro {ORANGE_MONEY_NUMBER}\n"
            f"3. Mets comme motif / référence : {reference}\n"
            f"4. Une fois le paiement fait, reviens ici et entre le code de transaction Orange Money."
        )
    }

@app.post("/api/redeem")
async def redeem(payload: RedeemRequest):
    """L'utilisateur soumet son ID de transaction après paiement."""
    with get_db() as conn:
        payment = conn.execute(
            "SELECT * FROM payments WHERE reference = ? AND user_id = ?",
            (payload.reference, payload.user_id)
        ).fetchone()

        if not payment:
            raise HTTPException(404, "Référence de paiement introuvable.")

        if payment["status"] == "approved":
            return {"message": "Ce paiement a déjà été validé. Les crédits sont déjà sur ton compte."}

        # On enregistre le transaction_id et on laisse en pending pour validation admin
        conn.execute(
            "UPDATE payments SET transaction_id = ?, status = 'pending' WHERE id = ?",
            (payload.transaction_id.strip(), payment["id"])
        )
        conn.commit()

    return {
        "message": (
            "✅ Demande enregistrée !\n\n"
            "Ton paiement est en cours de vérification. "
            "Les crédits seront ajoutés dès que le propriétaire validera la transaction "
            "(généralement sous 1h en journée).\n\n"
            "Tu peux aussi contacter le propriétaire avec ton code de transaction pour accélérer."
        ),
        "status": "pending"
    }

@app.get("/admin")
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.post("/api/admin/payments")
async def list_payments(password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(403, "Mot de passe incorrect")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/admin/approve")
async def approve_payment(payload: AdminApprove):
    if payload.password != ADMIN_PASSWORD:
        raise HTTPException(403, "Mot de passe incorrect")

    with get_db() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payload.payment_id,)).fetchone()
        if not payment:
            raise HTTPException(404, "Paiement introuvable")
        if payment["status"] == "approved":
            return {"message": "Déjà approuvé"}

        pack_type = payment["pack_type"] if "pack_type" in payment.keys() else "standard"
        is_premium = 1 if pack_type == "premium" else 0

        # Add credits + premium flag
        if is_premium:
            conn.execute(
                "UPDATE users SET credits = credits + ?, is_premium = 1 WHERE user_id = ?",
                (payment["messages"], payment["user_id"])
            )
        else:
            conn.execute(
                "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                (payment["messages"], payment["user_id"])
            )

        conn.execute(
            "UPDATE payments SET status = 'approved', approved_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), payload.payment_id)
        )
        conn.commit()

    pack_label = "Premium" if is_premium else "Standard"
    return {"message": f"✅ Pack {pack_label} validé : {payment['messages']} crédits ajoutés."}

@app.post("/api/admin/reject")
async def reject_payment(payment_id: int = Form(...), password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(403, "Mot de passe incorrect")
    with get_db() as conn:
        conn.execute(
            "UPDATE payments SET status = 'rejected' WHERE id = ?",
            (payment_id,)
        )
        conn.commit()
    return {"message": "Paiement rejeté"}

# Keep simple endpoints for compatibility
@app.post("/upload")
async def upload(file: UploadFile = File(...), message: str = Form(""), user_id: str = Form("anonymous")):
    user = get_or_create_user(user_id)
    allowed, _ = can_chat(user)
    if not allowed:
        return JSONResponse({"error": "no_credits", "reply": "Plus de crédits. Achète un pack."}, status_code=402)

    content = await file.read()
    # Simple text extraction attempt
    try:
        text = content.decode("utf-8", errors="ignore")[:4000]
    except Exception:
        text = "[Fichier binaire reçu]"

    prompt = f"L'utilisateur a envoyé un fichier nommé {file.filename}. Contenu extrait :\n{text}\n\nQuestion de l'utilisateur : {message or 'Analyse ce fichier.'}"
    reply = call_gemini(prompt)
    if not reply.startswith("⚠️"):
        consume_message(user_id)
    return {"reply": reply}

@app.post("/generate-image")
async def generate_image(request: Request):
    # Placeholder - real image gen needs Imagen or another service
    body = await request.json()
    prompt = body.get("prompt", "")
    return {
        "error": "La génération d'image n'est pas encore activée sur cette version. Utilise le chat pour décrire une image."
    }

@app.get("/health")
async def health():
    return {"status": "ok", "model": GEMINI_MODEL, "has_key": bool(GEMINI_API_KEY)}
