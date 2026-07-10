import eventlet
eventlet.monkey_patch()

import os
import json
import time
import requests
import threading
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_socketio import SocketIO

from auth import authenticate, generate_token, token_required, error_response, USERS
from data_store import store, iso_now

LIVE_UPDATE_INTERVAL = int(os.environ.get("LIVE_UPDATE_INTERVAL", "3"))
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
_origins = "*" if CORS_ORIGINS == "*" else [o.strip() for o in CORS_ORIGINS.split(",")]

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": _origins}})
socketio = SocketIO(app, cors_allowed_origins=_origins, async_mode="eventlet")

API = "/api/v1"


# ---------------------------------------------------------------------------
# Health check (useful for Render's health check + uptime pings)
# ---------------------------------------------------------------------------
@app.route("/")
@app.route("/health")
def health():
    return jsonify({"success": True, "service": "sortify-ai-backend", "status": "ok"})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route(f"{API}/auth/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    password = body.get("password")
    role = body.get("role")

    if not email or not password:
        return error_response("VALIDATION_ERROR", "Email and password are required.", 400)

    user, err_code, err_msg = authenticate(email, password, role)
    if not user:
        status = 401 if err_code == "INVALID_CREDENTIALS" else 403
        return error_response(err_code, err_msg, status)

    token = generate_token(user, email)
    return jsonify({
        "success": True,
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
    })


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route(f"{API}/dashboard/summary")
@token_required
def dashboard_summary():
    return jsonify({"success": True, **store.dashboard_summary()})


# ---------------------------------------------------------------------------
# Live sensor snapshot (poll-based; see /stream/live for push updates)
# ---------------------------------------------------------------------------
@app.route(f"{API}/sensors/live")
@token_required
def sensors_live():
    return jsonify({"success": True, **store.live})


# ---------------------------------------------------------------------------
# HTTP POST endpoint for AWS Lambda telemetry forwarding
# ---------------------------------------------------------------------------
@app.route(f"{API}/sensors/update", methods=["POST"])
def sensors_update():
    # Verify API Key if set in environment (optional security)
    api_key = request.headers.get("X-API-Key")
    expected_key = os.environ.get("LAMBDA_API_KEY")
    if expected_key and api_key != expected_key:
        return error_response("UNAUTHORIZED", "Invalid API Key.", 401)

    body = request.get_json(silent=True) or {}
    record = store.update_from_http_post(body, socketio)
    return jsonify({
        "success": True,
        "message": "Sensor data received and processed.",
        "event_logged": record is not None,
        "record": record
    })


# ---------------------------------------------------------------------------
# Waste history (paginated)
# ---------------------------------------------------------------------------
@app.route(f"{API}/waste/history")
@token_required
def waste_history():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        limit = min(max(int(request.args.get("limit", 20)), 1), 200)
    except ValueError:
        return error_response("VALIDATION_ERROR", "page and limit must be integers.", 400)

    start = (page - 1) * limit
    end = start + limit
    items = store.history[start:end]
    return jsonify({
        "success": True,
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": len(store.history),
            "totalPages": (len(store.history) + limit - 1) // limit,
        },
    })


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@app.route(f"{API}/analytics")
@token_required
def analytics():
    return jsonify({"success": True, **store.analytics()})


# ---------------------------------------------------------------------------
# Reports (paginated)
# ---------------------------------------------------------------------------
@app.route(f"{API}/reports")
@token_required
def reports():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        limit = min(max(int(request.args.get("limit", 30)), 1), 100)
    except ValueError:
        return error_response("VALIDATION_ERROR", "page and limit must be integers.", 400)

    start = (page - 1) * limit
    end = start + limit
    items = store.reports[start:end]
    return jsonify({
        "success": True,
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": len(store.reports),
            "totalPages": (len(store.reports) + limit - 1) // limit,
        },
    })


# ---------------------------------------------------------------------------
# Device status
# ---------------------------------------------------------------------------
@app.route(f"{API}/devices/status")
@token_required
def devices_status():
    return jsonify({"success": True, **store.device_status})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.route(f"{API}/settings", methods=["GET"])
@token_required
def get_settings():
    return jsonify({"success": True, "settings": store.settings})


@app.route(f"{API}/settings", methods=["PUT"])
@token_required
def update_settings():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return error_response("VALIDATION_ERROR", "Request body must be a JSON object.", 400)

    for key in ("device", "wifi", "aws", "camera", "thresholds", "theme"):
        if key in body:
            if isinstance(store.settings.get(key), dict) and isinstance(body[key], dict):
                store.settings[key].update(body[key])
            else:
                store.settings[key] = body[key]

    socketio.emit("settings_updated", store.settings)
    return jsonify({"success": True, "settings": store.settings})


# ---------------------------------------------------------------------------
# Server-Sent Events stream (alternative to WebSocket, works everywhere)
# GET /api/v1/stream/live?token=<JWT>   (EventSource can't set headers, so
# the token is accepted as a query param here in addition to the header)
# ---------------------------------------------------------------------------
@app.route(f"{API}/stream/live")
def stream_live():
    from auth import decode_token
    import jwt as pyjwt

    token = request.args.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        decode_token(token)
    except Exception:
        return error_response("UNAUTHORIZED", "Missing or invalid token.", 401)

    def event_stream():
        last_id = None
        while True:
            payload = json.dumps(store.live)
            yield f"event: sensor_update\ndata: {payload}\n\n"
            if store.history and store.history[0]["id"] != last_id:
                last_id = store.history[0]["id"]
                yield f"event: waste_event\ndata: {json.dumps(store.history[0])}\n\n"
            eventlet.sleep(LIVE_UPDATE_INTERVAL)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---------------------------------------------------------------------------
# S3 Latest Image Endpoint
# ---------------------------------------------------------------------------
AWS_API = "https://v0h6p4tfkb.execute-api.us-east-1.amazonaws.com/latestimage"

@app.route("/api/latestimage")
def latest_image():
    try:
        response = requests.get(AWS_API, timeout=3.0)
        if response.status_code == 200:
            return jsonify(response.json())
    except Exception as e:
        print(f"Error fetching latest image: {e}")
    return jsonify({"error": "Unable to fetch image"})


# ---------------------------------------------------------------------------
# Frontend Compatibility Endpoints (sortifyApi Client)
# ---------------------------------------------------------------------------
@app.route("/api/live/stream")
def sse_live_stream():
    def event_stream():
        last_id = None
        while True:
            if store.history and store.history[0]["id"] != last_id:
                last_id = store.history[0]["id"]
                payload = json.dumps(store.history[0])
                yield f"data: {payload}\n\n"
            eventlet.sleep(0.5)
    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    })

@app.route("/api/live/events")
def api_live_events():
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        limit = 20
    items = store.history[:limit]
    return jsonify({
        "count": len(items),
        "generatedAt": int(time.time() * 1000),
        "data": items
    })

@app.route("/api/live/telemetry")
def api_live_telemetry():
    return jsonify(store.live)

@app.route("/api/live/summary")
def api_live_summary():
    db_sum = store.dashboard_summary()
    last_pred = None
    if store.history:
        last_pred = {
            "waste": store.history[0]["waste"],
            "confidence": store.history[0]["confidence"],
            "inferenceMs": store.history[0]["inferenceMs"],
            "frameId": store.history[0]["frameId"]
        }
    return jsonify({
        **db_sum,
        "streaming": store.device_status["aws"] == "Connected",
        "connectedDevices": 1 if store.device_status["esp32"] == "Online" else 0,
        "eventsPerMinute": 12,
        "lastPrediction": last_pred,
        "avgProcessingMs": store.live["avgProcessingMs"],
        "modelVersion": "v2.3.1"
    })

@app.route("/api/live/camera/<cameraId>")
def api_live_camera(cameraId):
    return jsonify({
        "cameraId": cameraId,
        "resolution": "1920x1080",
        "fps": 30,
        "latencyMs": store.live["avgProcessingMs"],
        "frameId": store.history[0]["frameId"] if store.history else 1000,
        "timestamp": iso_now(),
        "streamUrl": "",
        "model": "YOLOv8n",
        "detections": []
    })


# ---------------------------------------------------------------------------
# Socket.IO real-time events
# ---------------------------------------------------------------------------
def background_broadcaster():
    """Runs forever in a green thread, simulating live telemetry pushes."""
    while True:
        socketio.sleep(LIVE_UPDATE_INTERVAL)
        new_record = store.tick()
        socketio.emit("sensor_update", store.live)
        socketio.emit("dashboard_update", store.dashboard_summary())
        if new_record:
            socketio.emit("waste_event", new_record)
            if new_record.get("status") == "Rejected":
                socketio.emit("alert", {
                    "level": "warning",
                    "message": f"Item at {new_record['timestamp']} was rejected during sorting.",
                    "timestamp": iso_now(),
                })


_broadcast_started = False


@app.before_request
def start_background_broadcaster_if_needed():
    global _broadcast_started
    if not _broadcast_started:
        _broadcast_started = True
        store.start_mqtt_client(socketio)
        socketio.start_background_task(background_broadcaster)


@socketio.on("connect")
def on_connect():
    global _broadcast_started
    socketio.emit("sensor_update", store.live, to=request.sid)
    socketio.emit("device_status", store.device_status, to=request.sid)
    if not _broadcast_started:
        _broadcast_started = True
        store.start_mqtt_client(socketio)
        socketio.start_background_task(background_broadcaster)


# ---------------------------------------------------------------------------
# 404 handler -> keep consistent error shape
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return error_response("NOT_FOUND", "The requested resource was not found.", 404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
