"""JWT authentication helpers for the SORTIFY AI demo backend.

Demo users live in-memory below. Swap USERS / verify logic for a real DB
(Postgres, DynamoDB, etc.) when you move past the prototype stage.
"""

import os
import jwt
import datetime
from functools import wraps
from flask import request, jsonify

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

# Demo credentials: email -> {password, name, role, id}
USERS = {
    "admin@sortify.com": {
        "id": 1, "name": "Admin", "password": "password", "role": "Administrator",
    },
    "supervisor@sortify.com": {
        "id": 2, "name": "Supervisor", "password": "password", "role": "Supervisor",
    },
    "operator@sortify.com": {
        "id": 3, "name": "Operator", "password": "password", "role": "Operator",
    },
    "maintenance@sortify.com": {
        "id": 4, "name": "Maintenance", "password": "password", "role": "Maintenance",
    },
}


def error_response(code, message, status=400):
    return jsonify({
        "success": False,
        "error": {"code": code, "message": message},
    }), status


def authenticate(email, password, role):
    user = USERS.get(email)
    if not user or user["password"] != password:
        return None, "INVALID_CREDENTIALS", "Invalid email or password."
    if role and user["role"] != role:
        return None, "ROLE_MISMATCH", "Role does not match this account."
    return user, None, None


def generate_token(user, email):
    payload = {
        "sub": email,
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response(
                "UNAUTHORIZED", "Missing or malformed Authorization header.", 401
            )
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return error_response("TOKEN_EXPIRED", "Token has expired.", 401)
        except jwt.InvalidTokenError:
            return error_response("INVALID_TOKEN", "Token is invalid.", 401)
        request.user = payload
        return f(*args, **kwargs)
    return decorated
