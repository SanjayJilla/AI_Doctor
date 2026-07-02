#give code for login user
import os
from flask import Blueprint, Flask, app, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from src.database import db, User



load_dotenv()

auth_bp = Blueprint('auth', __name__)

#post /api/auth/register
@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    username = data.get('username',"").strip()
    email = data.get('email',"").strip().lower()
    password = data.get('password',"").strip()

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    # Check if user already exists
    
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already exists"}), 400

    #hash the password
    hashed_password = generate_password_hash(password)
    # Some User models don't accept kwargs in the constructor; set attributes explicitly
    new_user = User()
    new_user.username = username
    new_user.email = email
    new_user.password = hashed_password
    db.session.add(new_user)
    db.session.commit()
    token = create_access_token(identity=str(new_user.id))
    return jsonify({"message": "Account created successfully", "token": token, "user": new_user.to_dict()}), 201

#post /api/auth/login
@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    email = data.get('email',"").strip().lower()
    password = data.get('password',"").strip()

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid email or password"}), 401

    access_token = create_access_token(identity=str(user.id))
    return jsonify({"token": access_token, "user": user.to_dict()}), 200

#get current user
#get /api/auth/me
@auth_bp.route("/api/auth/me", methods=["GET"])
@jwt_required()
def me():
    from flask_jwt_extended import get_jwt_identity,verify_jwt_in_request
    try:
        verify_jwt_in_request()
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": user.to_dict()}), 200
    except Exception:
        return jsonify({"error": "Invalid or missing token"}), 401

