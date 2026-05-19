# ─────────────────────────────────────────────────────────────
# app.py  —  Flask backend for Medical AI Chatbot
# Run: python app.py
# ─────────────────────────────────────────────────────────────

import os
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from src.database import db, save_chat, get_user_history, get_recent_context, Chat
from src.auth import auth_bp
from src.helper import get_embeddings, get_vectorstore, ask_medical_question, check_symptoms

load_dotenv()

app = Flask(__name__)
CORS(app)
jwt = JWTManager(app) # Initialize JWTManager with the Flask app
app.register_blueprint(auth_bp)  # Register the authentication blueprint
#medical.db file is created automatically
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///medical.db"
app.config["SQLALCHEMY_TRACK_EXPIRES"] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY','medical-secret-fallback-key-999')
db.init_app(app)  # Initialize SQLAlchemy with the Flask app


with app.app_context():
    db.create_all()  # Create tables if they don't exist
    print("Database tables created or already exist.")


print("\nLoading embeddings & vectorstore...")
try:
    _embeddings = get_embeddings()
    _vectorstore = get_vectorstore(_embeddings)
    print("Vectorstore ready!\n")
except Exception as e:
    print(f"Vectorstore load failed: {e}")
    print("   Run ingestion first: python ingest.py\n")
    _vectorstore = None

@app.route("/")
def login_page():
    return render_template("login.html")


@app.route("/signup-page")
def signup_page():
    return render_template("signup.html")


@app.route("/chat-page")
def chat_page():
    return render_template("chat.html")


@app.route("/api/ask", methods=["POST"])
@jwt_required()
def ask():
    
    if _vectorstore is None:
        return jsonify({
            "error": "Knowledge base not loaded. Run 'python ingest.py' first."
        }), 503

    data = request.get_json()
    if not data or not data.get("question", "").strip():
        return jsonify({"error": "Missing or empty 'question' field"}), 400

    question = data["question"].strip()
    user_id = get_jwt_identity()
    recent_context = get_recent_context(user_id, limit=5)
    try:
        result = ask_medical_question(question, _vectorstore, recent_context)
        save_chat(
            user_id=user_id,
            question=question,
            answer=result["answer"],
            source=result.get("source", ""),
            layer=result.get("layer", 1),
        )
        return jsonify(result)
    except Exception as e:
        print(f"/api/ask error: {e}")
        return jsonify({"error": "Something went wrong. Please try again."}), 500


@app.route("/api/symptoms", methods=["POST"])
@jwt_required()
def symptoms():
    
    if _vectorstore is None:
        return jsonify({"error": "Knowledge base not loaded."}), 503

    data = request.get_json()
    if not data or not data.get("symptoms", "").strip():
        return jsonify({"error": "Missing or empty 'symptoms' field"}), 400
    user_id = get_jwt_identity()
    symptoms_text = data["symptoms"].strip()

    try:
        result = check_symptoms(symptoms_text, _vectorstore)
        save_chat(
            user_id=user_id,
            question=f"[symptoms]{symptoms_text}",
            answer=result["answer"],
            source="Symptom Checker",
            layer=result.get("layer", 1),
        )
        return jsonify(result)
    except Exception as e:
        print(f"/api/symptoms error: {e}")
        return jsonify({"error": "Something went wrong. Please try again."}), 500



@app.route("/api/history",methods=["GET"])
@jwt_required()
def history():
    user_id=get_jwt_identity()
    chats=get_user_history(user_id,limit=20)
    return jsonify({"chats":chats})


@app.route("/api/history/clear",methods=["DELETE"])
@jwt_required()
def clear_history():
    from src.database import Chat
    user_id=get_jwt_identity()
    Chat.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({"message":"History cleared"})



@app.route("/api/health", methods=["GET"])
def health():
    """Health check — confirms API and vectorstore are running."""
    return jsonify({
        "status": "ok",
        "vectorstore": "loaded" if _vectorstore else "not loaded",
        "model": "llama-3.1-8b-instant",
        "provider": "Groq",
        
    })

if __name__ == "__main__":
    port  = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    print(f"MediBot running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)