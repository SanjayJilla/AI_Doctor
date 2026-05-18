#sqlite database initialization
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

db= SQLAlchemy()  # Initialize SQLAlchemy without app for now   
#table 1 store registered user data
#id, username,email,password (hashed)
#create when they register

class User(db.Model):
    __tablename__="users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # Store hashed password
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    chats=db.relationship('Chat', backref='user', lazy=True)  # One-to-many relationship with Chat  

    def to_dict(self):
        #convert user to dict (safe to send to frontend - no password)
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.strftime("%b %Y")
        }
    


#table 2 chats
#store every single message exchange
# id ,user_id, question, answerm source, layer , created

class Chat(db.Model):
    __tablename__="chats"

    id = db.Column(db.Integer, primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("users.id"),nullable=False)
    question=db.Column(db.Text,nullable=False)
    answer=db.Column(db.Text,nullable=False)
    source=db.Column(db.String(200),nullable=True)
    layer=db.Column(db.Integer,nullable=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "layer": self.layer,
            "created_at": self.created_at.strftime("%b %Y")
        }
    
#database helper functions

def save_chat(user_id, question, answer, source= "", layer=1):
    """Save a chat exchange to the database."""
    # Create instance and set attributes to avoid static analysis warnings
    chat = Chat()
    chat.user_id = user_id
    chat.question = question
    chat.answer = answer
    chat.source = source
    chat.layer = layer
    db.session.add(chat)
    db.session.commit()
    return chat


def get_user_history(user_id, limit=20):
    """Get the most recent chat history for a user."""
    chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.created_at.desc()).limit(limit).all()
    return [chat.to_dict() for chat in chats]

def get_recent_context(user_id, limit=5):
    """Get the most recent chats for context in RAG."""
    chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.created_at.desc()).limit(limit).all()
    chats=list(reversed(chats))  # Reverse to get oldest first
    if not chats:
        return ""
    lines=[]
    for chat in chats:
        lines.append(f"Q: {chat.question}")
        lines.append(f"A: {chat.answer[:300]}")
    return "\n".join(lines)



