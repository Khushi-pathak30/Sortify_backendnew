# SORTIFY AI — Backend API

Flask backend implementing the SORTIFY AI Smart Waste Segregation Dashboard
API spec: JWT auth, dashboard/analytics/reports endpoints, device status,
settings, and real-time telemetry via **Socket.IO** (WebSocket) and **SSE**
(Server-Sent Events) as a fallback.

All data is generated in-memory (`data_store.py`) so the frontend can be
built and demoed today, then pointed at real ESP32 / AWS IoT data later
without changing any routes or response shapes.

## 1. Run locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit JWT_SECRET
python app.py
```

Server runs on `http://localhost:5000`.

## 2. Demo login credentials

| Email                     | Password | Role           |
|----------------------------|----------|----------------|
| admin@sortify.com         | password | Administrator  |
| supervisor@sortify.com    | password | Supervisor     |
| operator@sortify.com      | password | Operator       |
| maintenance@sortify.com   | password | Maintenance    |

## 3. Deploy to Render

**Option A — Blueprint (recommended, one click):**
1. Push this folder to a GitHub repo.
2. In Render: **New > Blueprint**, point at the repo (it reads `render.yaml`).
3. Render provisions the service, auto-generates `JWT_SECRET`, and deploys.

**Option B — Manual Web Service:**
1. **New > Web Service**, connect your repo.
2. Environment: `Python 3`
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn --worker-class eventlet -w 1 --timeout 120 app:app`
5. Add environment variables from `.env.example` (at minimum set `JWT_SECRET`).
6. Health check path: `/health`

Once deployed, your base URL will be something like
`https://sortify-ai-backend.onrender.com`. In your Lovable/frontend project,
set `VITE_API_BASE_URL=https://sortify-ai-backend.onrender.com/api/v1` and
`VITE_SOCKET_URL=https://sortify-ai-backend.onrender.com`.

> Render's free tier spins down after inactivity — the first request after
> idle can take ~30-50s to respond while it wakes up.

## 4. API Reference

Base URL: `/api/v1`. All routes except `/auth/login` and `/health` require:
`Authorization: Bearer <token>`.

### Auth
`POST /auth/login`
```json
{ "email": "admin@sortify.com", "password": "password", "role": "Administrator" }
```
Returns `{ success, token, user }`.

### Dashboard
`GET /dashboard/summary` → totalWaste, metalWaste, wetWaste, dryWaste, avgMoisture, systemStatus, awsStatus, esp32Status.

### Live sensors
`GET /sensors/live` → current metal/moisture/ir/proximity/servo/camera/cloud snapshot.

### Waste history (paginated)
`GET /waste/history?page=1&limit=20` → `{ data: [...], pagination: {...} }`

### Analytics
`GET /analytics` → distribution %, dailyCollection[], weeklyTrend[].

### Reports (paginated)
`GET /reports?page=1&limit=30` → daily aggregate reports, last 30 days by default.

### Device status
`GET /devices/status` → per-component online/active/idle status.

### Settings
`GET /settings` → current config.
`PUT /settings` → partial update, body may include any of
`device, wifi, aws, camera, thresholds, theme`.

### Real-time updates

**Socket.IO** (preferred): connect to the base URL, listen for events:
- `sensor_update` — every `LIVE_UPDATE_INTERVAL` seconds (default 3s)
- `dashboard_update` — KPI recompute alongside each sensor tick
- `waste_event` — emitted when a new item is sorted
- `device_status` — sent on connect
- `alert` — emitted on rejected/anomalous sorts
- `settings_updated` — emitted after a successful `PUT /settings`

```js
import { io } from "socket.io-client";
const socket = io("https://sortify-ai-backend.onrender.com");
socket.on("sensor_update", (data) => console.log(data));
```

**SSE fallback**: `GET /api/v1/stream/live?token=<JWT>` streams
`sensor_update` and `waste_event` server-sent events on the same interval.

### Error format

```json
{ "success": false, "error": { "code": "DEVICE_OFFLINE", "message": "ESP32 is not connected." } }
```

## 5. Project structure

```
sortify-backend/
├── app.py            # Flask app, routes, Socket.IO + SSE real-time layer
├── auth.py           # JWT auth helpers + demo user store
├── data_store.py      # Dummy data generators + in-memory Store class
├── requirements.txt
├── Procfile           # gunicorn start command (Render/Heroku)
├── render.yaml         # Render Blueprint definition
├── .env.example
└── .gitignore
```

## 6. Moving from dummy data to real telemetry

Everything reads from the single `store` object in `data_store.py`. To wire
up real ESP32/AWS data:
- Replace `store.tick()` with a handler that ingests real MQTT/AWS IoT
  messages and updates `store.live` / appends to `store.history`.
- Keep the response shapes identical and the frontend needs zero changes.
