import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
  from google import genai
except ImportError:
  genai = None

app = FastAPI(
    title="HAIDARA AI",
    description="Assistant intelligent HAIDARA AI",
    version="1.1.0",
)

BASE_DIR = Path(__file__).resolve().parent
app.mount(
    "/static", StaticFiles(directory=BASE_DIR / "static"), name="static"
)

SYSTEM_INSTRUCTION = (
    "Tu es HAIDARA AI, un assistant intelligent, clair, pédagogique et"
    " précis. Réponds en français par défaut. Pour les questionnaires, QCM,"
    " exercices ou dissertations, donne la bonne réponse ou la démarche"
    " complète, explique pourquoi, et structure avec des titres ou listes"
    " quand cela aide à la compréhension."
)


class MessageEntree(BaseModel):
  message: str


def reponse_locale_secours(texte: str) -> str:
  m = texte.strip()
  bas = m.lower()
  if not m:
    return "Écris-moi une question ou un questionnaire pour que je puisse t'aider."
  if any(s in bas for s in ["bonjour", "salut", "bonsoir", "coucou", "hey"]):
    return (
        "Bonjour ! Je suis **HAIDARA AI**. Envoie-moi ta question, ton"
        " exercice ou ton questionnaire."
    )
  return (
      f"**HAIDARA AI (mode local)** a reçu : *« {m} »*.\n\n"
      "Pour activer les réponses complètes type IA sur tous les"
      " questionnaires, définis la variable `GEMINI_API_KEY` dans CMD avant de"
      " lancer Uvicorn."
  )


def generer_reponse_ia(texte: str) -> str:
  msg = texte.strip()
  if not msg:
    return reponse_locale_secours(msg)

  api_key = os.environ.get("GEMINI_API_KEY", "").strip()
  if not api_key or genai is None:
    return reponse_locale_secours(msg)

  try:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=msg,
        config={"system_instruction": SYSTEM_INSTRUCTION},
    )
    return response.text or "Aucune réponse générée."
  except Exception as exc:
    return (
        "Erreur lors de l'appel à l'API IA : "
        f"`{exc}`\n\n"
        + reponse_locale_secours(msg)
    )


@app.get("/bonjour")
def bonjour():
  return {"message": "Bonjour"}


@app.post("/chat")
def discuter(data: MessageEntree):
  return {"reponse": generer_reponse_ia(data.message)}


@app.get("/", response_class=HTMLResponse)
def interface_chat():
  return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta name="theme-color" content="#0f172a" />
        <link rel="manifest" href="/static/manifest.json" />
        <link rel="icon" href="/static/icon-192.png" />
        <title>HAIDARA AI</title>
        <style>
            :root {
                --bg: #0b1120;
                --panel: #0f172a;
                --card: #1e293b;
                --user: #2563eb;
                --accent: #10b981;
                --text: #f8fafc;
                --muted: #94a3b8;
                --border: #334155;
            }
            * { box-sizing: border-box; }
            body {
                margin: 0;
                font-family: "Segoe UI", Arial, sans-serif;
                background: var(--bg);
                color: var(--text);
                display: flex;
                flex-direction: column;
                height: 100vh;
            }
            header {
                background: var(--panel);
                border-bottom: 1px solid var(--border);
                padding: 14px 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            .brand {
                display: flex;
                align-items: center;
                gap: 10px;
                font-weight: 700;
                font-size: 18px;
            }
            .dot {
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: var(--accent);
            }
            .badge {
                font-size: 12px;
                color: var(--muted);
                background: var(--card);
                padding: 4px 10px;
                border-radius: 999px;
                border: 1px solid var(--border);
            }
            #messages {
                flex: 1;
                overflow-y: auto;
                padding: 20px;
                display: flex;
                flex-direction: column;
                gap: 14px;
                max-width: 900px;
                width: 100%;
                margin: 0 auto;
            }
            .msg {
                max-width: 82%;
                padding: 13px 16px;
                border-radius: 14px;
                line-height: 1.55;
                font-size: 15px;
                white-space: pre-line;
                word-wrap: break-word;
            }
            .user {
                align-self: flex-end;
                background: var(--user);
                color: #ffffff;
                border-bottom-right-radius: 4px;
            }
            .ia {
                align-self: flex-start;
                background: var(--card);
                color: var(--text);
                border: 1px solid var(--border);
                border-bottom-left-radius: 4px;
            }
            .footer-wrap {
                background: var(--panel);
                border-top: 1px solid var(--border);
                padding: 12px 16px;
            }
            form {
                max-width: 900px;
                margin: 0 auto;
                display: flex;
                gap: 10px;
            }
            input {
                flex: 1;
                padding: 13px 16px;
                border-radius: 10px;
                border: 1px solid var(--border);
                background: var(--bg);
                color: var(--text);
                font-size: 15px;
                outline: none;
            }
            input:focus {
                border-color: var(--accent);
            }
            button {
                padding: 13px 20px;
                border-radius: 10px;
                border: none;
                background: var(--accent);
                color: #042f2e;
                font-weight: 700;
                font-size: 15px;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <header>
            <div class="brand">
                <span class="dot"></span>
                <span>HAIDARA AI</span>
            </div>
            <span class="badge">PWA + IA v1.1</span>
        </header>

        <div id="messages">
            <div class="msg ia">Bienvenue sur <strong>HAIDARA AI</strong>. Pose-moi une question ou envoie un questionnaire complet.</div>
        </div>

        <div class="footer-wrap">
            <form id="chat-form">
                <input id="champ" type="text" placeholder="Écris ton message ou ton questionnaire..." autocomplete="off" required />
                <button type="submit">Envoyer</button>
            </form>
        </div>

        <script>
            if ("serviceWorker" in navigator) {
                navigator.serviceWorker.register("/static/service-worker.js");
            }

            const form = document.getElementById("chat-form");
            const champ = document.getElementById("champ");
            const messages = document.getElementById("messages");

            function formaterTexte(texte) {
                return texte
                    .replace(/&/g, "&")
                    .replace(/</g, "<")
                    .replace(/>/g, ">")
                    .replace(/\\*\\*(.*?)\\*\\*/g, "<strong>$1</strong>")
                    .replace(/\\*(.*?)\\*/g, "<em>$1</em>");
            }

            function ajouterBulle(texte, auteur) {
                const div = document.createElement("div");
                div.className = "msg " + auteur;
                if (auteur === "ia") {
                    div.innerHTML = formaterTexte(texte);
                } else {
                    div.textContent = texte;
                }
                messages.appendChild(div);
                messages.scrollTop = messages.scrollHeight;
            }

            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                const texte = champ.value.trim();
                if (!texte) return;
                ajouterBulle(texte, "user");
                champ.value = "";

                ajouterBulle("Réflexion en cours...", "ia");
                const bulleAttente = messages.lastElementChild;

                try {
                    const res = await fetch("/chat", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ message: texte })
                    });
                    const data = await res.json();
                    bulleAttente.innerHTML = formaterTexte(data.reponse);
                } catch (err) {
                    bulleAttente.textContent = "Erreur de connexion au serveur HAIDARA AI.";
                }
            });
        </script>
    </body>
    </html>
    """