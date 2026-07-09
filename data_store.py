"""
In-memory data store for the SORTIFY AI demo backend.

This module generates realistic-looking dummy industrial IoT data so the
frontend can be fully wired up before real ESP32 / AWS telemetry exists.
It also includes paho-mqtt client connection to subscribe to AWS IoT Core
topics and update the state in real-time.
"""

import os
import ssl
import time
import random
import json
from datetime import datetime, timedelta, timezone
import paho.mqtt.client as mqtt

WASTE_TYPES = ["Plastic", "Paper", "Metal", "Organic", "Glass", "E-Waste", "Cardboard"]

# Non-static random seeding for unique values across boots
random.seed(time.time())


def format_pem(pem_str):
    if not pem_str:
        return ""
    pem_str = pem_str.strip().replace("\\n", "\n")
    
    if "-----BEGIN" in pem_str:
        header_types = ["RSA PRIVATE KEY", "PRIVATE KEY", "CERTIFICATE"]
        selected_type = "CERTIFICATE"
        for t in header_types:
            if t in pem_str:
                selected_type = t
                break
        
        begin_tag = f"-----BEGIN {selected_type}-----"
        end_tag = f"-----END {selected_type}-----"
        
        # Extract body and remove all whitespace/spaces
        body = pem_str.replace(begin_tag, "").replace(end_tag, "")
        body = "".join(body.split())
        
        # Re-wrap body to 64-char lines
        wrapped_body = "\n".join(body[i:i+64] for i in range(0, len(body), 64))
        return f"{begin_tag}\n{wrapped_body}\n{end_tag}\n"
        
    return pem_str


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(dt: datetime):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify(metal, moisture, ir):
    if metal:
        return "Metal"
    if moisture is not None and moisture >= 45:
        return "Organic"
    if ir:
        return "Plastic"
    return random.choice(WASTE_TYPES)


def generate_live_events(rows=140):
    """Generate historical waste sorting records in the format expected by the frontend."""
    events = []
    now = datetime.now(timezone.utc)
    for i in range(rows):
        ts = now - timedelta(minutes=i * 7 + random.randint(0, 4))
        epoch_ms = int(ts.timestamp() * 1000)
        metal = random.random() < 0.28
        moisture = round(random.uniform(15, 70), 1)
        ir = random.random() < 0.6
        waste_type = _classify(metal, moisture, ir)
        events.append({
            "id": f"EVT-{epoch_ms}-{i}",
            "timestamp": epoch_ms,
            "device": f"ESP32-{random.randint(1, 9):03d}",
            "bin": f"BIN-{random.randint(1, 12):04d}",
            "area": random.choice(["Sector A - Conveyor", "Sector B - Recycling", "Sector C - Organic"]),
            "waste": waste_type,
            "confidence": round(random.uniform(0.75, 0.99), 3),
            "weightKg": round(random.uniform(0.05, 1.8), 2),
            "inferenceMs": random.randint(30, 220),
            "frameId": 10000 + i
        })
    return events


def generate_reports(days=30):
    """Generate daily aggregate reports for the previous N days."""
    reports = []
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        date = today - timedelta(days=i)
        metal = random.randint(20, 45)
        wet = random.randint(40, 75)
        dry = random.randint(35, 60)
        total = metal + wet + dry
        accuracy = round(random.uniform(92.5, 98.5), 1)
        reports.append({
            "date": date.isoformat(),
            "totalWaste": total,
            "metal": metal,
            "wet": wet,
            "dry": dry,
            "accuracy": accuracy,
        })
    return reports


def generate_weekly_trend():
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [{"day": d, "weight": random.randint(95, 165)} for d in days]


def generate_daily_collection(days=14):
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        out.append({"date": date.isoformat(), "weight": random.randint(95, 165)})
    return out


def default_settings():
    return {
        "device": {
            "deviceName": "SORTIFY-EDGE-01",
            "firmwareVersion": "1.4.2",
            "location": "Sorting Line A",
        },
        "wifi": {
            "ssid": "SORTIFY_IOT_NET",
            "security": "WPA2",
            "autoReconnect": True,
        },
        "aws": {
            "region": "ap-south-1",
            "iotEndpoint": "a1b2c3d4e5-ats.iot.ap-south-1.amazonaws.com",
            "topic": "sortify/telemetry",
        },
        "camera": {
            "resolution": "1280x720",
            "fps": 15,
            "detectionEnabled": True,
        },
        "thresholds": {
            "moistureWetPercent": 45,
            "metalSensitivity": 0.7,
            "irDetectionRange": 20,
        },
        "theme": "dark",
    }


class Store:
    """Simple in-memory state, safe enough for a single-process demo deploy."""

    def __init__(self):
        self.history = generate_live_events(140)
        self.reports = generate_reports(30)
        self.weekly_trend = generate_weekly_trend()
        self.daily_collection = generate_daily_collection(14)
        self.settings = default_settings()
        self.device_status = {
            "esp32": "Online",
            "camera": "Online",
            "metalSensor": "Active",
            "moistureSensor": "Active",
            "irSensor": "Active",
            "servo": "Idle",
            "aws": "Disconnected",
        }
        self.live = self._make_live_reading()
        self.mqtt_client = None

    def _make_live_reading(self):
        return {
            "device": "ESP32-001",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "distanceCm": random.randint(5, 120),
            "metalDetected": random.random() < 0.25,
            "irActive": random.random() < 0.6,
            "servoAngle": random.choice([0, 45, 90, 135, 180]),
            "wifiDbm": -30 - random.randint(0, 60),
            "cloudConnected": self.device_status["aws"] == "Connected",
            "objectsInFrame": random.randint(0, 3),
            "avgProcessingMs": random.randint(30, 200)
        }

    def tick(self):
        """Advance the simulated live sensor state by one step and log a
        waste record occasionally, mimicking a real detection event."""
        # Only run simulation updates if AWS MQTT is NOT connected
        if self.device_status["aws"] == "Connected":
            return None

        self.live = self._make_live_reading()

        if random.random() < 0.85:
            epoch_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            waste_type = random.choice(WASTE_TYPES)
            record = {
                "id": f"EVT-{epoch_ms}-sim",
                "timestamp": epoch_ms,
                "device": self.live["device"],
                "bin": f"BIN-{random.randint(1, 12):04d}",
                "area": "Sector A - Conveyor",
                "waste": waste_type,
                "confidence": round(random.uniform(0.75, 0.99), 3),
                "weightKg": round(random.uniform(0.05, 1.8), 2),
                "inferenceMs": self.live["avgProcessingMs"],
                "frameId": random.randint(20000, 30000)
            }
            self.history.insert(0, record)
            return record
        return None

    def dashboard_summary(self):
        metal_count = sum(1 for r in self.history if r["waste"] == "Metal")
        wet_count = sum(1 for r in self.history if r["waste"] == "Organic")
        plastic_count = sum(1 for r in self.history if r["waste"] == "Plastic")
        paper_count = sum(1 for r in self.history if r["waste"] == "Paper")
        unidentified_count = sum(1 for r in self.history if r["waste"] not in ["Metal", "Organic", "Plastic", "Paper"])

        metal_kg = round(metal_count * 0.9, 1) or 32
        wet_kg = round(wet_count * 1.1, 1) or 61
        plastic_kg = round(plastic_count * 0.75, 1) or 25
        paper_kg = round(paper_count * 0.5, 1) or 18
        unidentified_kg = round(unidentified_count * 0.6, 1) or 12
        total = round(metal_kg + wet_kg + plastic_kg + paper_kg + unidentified_kg, 1)
        avg_moisture = 35.5

        return {
            "totalWaste": total,
            "metalWaste": metal_kg,
            "wetWaste": wet_kg,
            "plasticWaste": plastic_kg,
            "paperWaste": paper_kg,
            "unidentifiedWaste": unidentified_kg,
            "avgMoisture": avg_moisture,
            "systemStatus": "Healthy",
            "awsStatus": self.device_status["aws"],
            "esp32Status": self.device_status["esp32"],
        }

    def analytics(self):
        total = max(len(self.history), 1)
        metal_count = sum(1 for r in self.history if r["waste"] == "Metal")
        wet_count = sum(1 for r in self.history if r["waste"] == "Organic")
        dry_count = total - metal_count - wet_count
        return {
            "distribution": {
                "metal": round(metal_count / total * 100, 1),
                "wet": round(wet_count / total * 100, 1),
                "dry": round(dry_count / total * 100, 1),
            },
            "dailyCollection": self.daily_collection,
            "weeklyTrend": self.weekly_trend,
        }

    def update_from_telemetry(self, data, socketio=None):
        """Update telemetry fields from raw data incoming from AWS IoT Core."""
        self.live = {
            "device": data.get("device", "ESP32-001"),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "distanceCm": int(data.get("distanceCm", data.get("distance_cm", 0))),
            "metalDetected": bool(data.get("metalDetected", data.get("metal", False))),
            "irActive": bool(data.get("irActive", data.get("ir", False))),
            "servoAngle": int(data.get("servoAngle", data.get("servo_angle", 0))),
            "wifiDbm": int(data.get("wifiDbm", data.get("wifi_dbm", -50))),
            "cloudConnected": True,
            "objectsInFrame": int(data.get("objectsInFrame", data.get("objects_in_frame", 0))),
            "avgProcessingMs": int(data.get("avgProcessingMs", data.get("avg_processing_ms", 50)))
        }
        
        self.device_status["aws"] = "Connected"
        self.device_status["esp32"] = "Online"
        
        if socketio:
            socketio.emit("sensor_update", self.live)
            socketio.emit("dashboard_update", self.dashboard_summary())

        is_event = bool(data.get("is_event", data.get("isEvent", False)))
        if is_event:
            waste_type = data.get("waste", data.get("type", "Plastic"))
            epoch_ms = self.live["timestamp"]
            record = {
                "id": f"EVT-{epoch_ms}-mqtt",
                "timestamp": epoch_ms,
                "device": self.live["device"],
                "bin": data.get("bin", f"BIN-{random.randint(1, 12):04d}"),
                "area": data.get("area", "Sector A - Conveyor"),
                "waste": waste_type,
                "confidence": float(data.get("confidence", 0.95)),
                "weightKg": float(data.get("weightKg", data.get("weight_kg", 0.2))),
                "inferenceMs": self.live["avgProcessingMs"],
                "frameId": int(data.get("frameId", data.get("frame_id", 0)))
            }
            self.history.insert(0, record)
            if socketio:
                socketio.emit("waste_event", record)
                if data.get("status") == "Rejected":
                    socketio.emit("alert", {
                        "level": "warning",
                        "message": f"Item at {datetime.now(timezone.utc).strftime('%H:%M:%S')} was rejected during sorting.",
                        "timestamp": iso_now()
                    })
            return record
        return None

    def start_mqtt_client(self, socketio=None):
        """Configure and start the AWS IoT Core MQTT client if certificates are available."""
        AWS_IOT_ENDPOINT = os.environ.get("AWS_IOT_ENDPOINT", self.settings["aws"]["iotEndpoint"])
        AWS_IOT_TOPIC = os.environ.get("AWS_IOT_TOPIC", self.settings["aws"]["topic"])
        AWS_IOT_CA_CERT = os.environ.get("AWS_IOT_CA_CERT")
        AWS_IOT_CLIENT_CERT = os.environ.get("AWS_IOT_CLIENT_CERT")
        AWS_IOT_CLIENT_KEY = os.environ.get("AWS_IOT_CLIENT_KEY")

        cert_dir = os.path.join(os.path.dirname(__file__), "certs")
        os.makedirs(cert_dir, exist_ok=True)
        ca_path = os.path.join(cert_dir, "AmazonRootCA1.pem")
        cert_path = os.path.join(cert_dir, "certificate.pem.crt")
        key_path = os.path.join(cert_dir, "private.pem.key")

        if AWS_IOT_CA_CERT:
            with open(ca_path, "w") as f:
                f.write(format_pem(AWS_IOT_CA_CERT))
        if AWS_IOT_CLIENT_CERT:
            with open(cert_path, "w") as f:
                f.write(format_pem(AWS_IOT_CLIENT_CERT))
        if AWS_IOT_CLIENT_KEY:
            with open(key_path, "w") as f:
                f.write(format_pem(AWS_IOT_CLIENT_KEY))

        if os.path.exists(ca_path) and os.path.exists(cert_path) and os.path.exists(key_path):
            try:
                client = mqtt.Client(client_id="SortifyBackendServer", transport="tcp")
                client.tls_set(
                    ca_certs=ca_path,
                    certfile=cert_path,
                    keyfile=key_path,
                    cert_reqs=ssl.CERT_REQUIRED,
                    tls_version=ssl.PROTOCOL_TLSv1_2,
                    ciphers=None
                )
                
                def on_connect(c, userdata, flags, rc):
                    if rc == 0:
                        print("AWS IoT Core: Connected successfully")
                        self.device_status["aws"] = "Connected"
                        c.subscribe(AWS_IOT_TOPIC)
                    else:
                        print(f"AWS IoT Core: Connection failed with code {rc}")
                        self.device_status["aws"] = "Disconnected"

                def on_message(c, userdata, msg):
                    try:
                        payload = json.loads(msg.payload.decode("utf-8"))
                        self.update_from_telemetry(payload, socketio)
                    except Exception as e:
                        print(f"AWS IoT Core: Error parsing message: {e}")

                client.on_connect = on_connect
                client.on_message = on_message
                client.connect(AWS_IOT_ENDPOINT, 8883, keepalive=60)
                client.loop_start()
                self.mqtt_client = client
                self.device_status["aws"] = "Connected"
                print("AWS IoT Core: MQTT listener client thread started.")
            except Exception as e:
                print(f"AWS IoT Core: Failed to start MQTT client: {e}")
                self.device_status["aws"] = "Disconnected"
        else:
            print("AWS IoT Core: Cert files not found. Running in simulated telemetry mode.")
            self.device_status["aws"] = "Disconnected"


store = Store()
