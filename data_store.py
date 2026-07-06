"""
In-memory data store for the SORTIFY AI demo backend.

This module generates realistic-looking dummy industrial IoT data so the
frontend can be fully wired up before real ESP32 / AWS telemetry exists.
Everything here is deliberately swappable: replace the generator functions
with real database / MQTT / AWS IoT reads later without touching the routes.
"""

import random
from datetime import datetime, timedelta, timezone

WASTE_TYPES = ["Metal", "Wet", "Dry"]
STATUSES = ["Sorted", "Rejected"]

random.seed(42)  # reproducible demo data


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(dt: datetime):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify(metal, moisture, ir):
    if metal:
        return "Metal"
    if moisture is not None and moisture >= 45:
        return "Wet"
    if ir:
        return "Dry"
    return random.choice(WASTE_TYPES)


def generate_waste_history(rows=140):
    """Generate historical waste sorting records, newest first."""
    history = []
    now = datetime.now(timezone.utc)
    for i in range(rows):
        ts = now - timedelta(minutes=i * 7 + random.randint(0, 4))
        metal = random.random() < 0.28
        moisture = round(random.uniform(15, 70), 1)
        ir = random.random() < 0.6
        proximity = random.random() < 0.85
        waste_type = _classify(metal, moisture, ir)
        status = "Sorted" if random.random() < 0.93 else "Rejected"
        history.append({
            "id": rows - i,
            "time": ts.strftime("%H:%M:%S"),
            "timestamp": iso(ts),
            "metal": metal,
            "moisture": moisture,
            "ir": "Detected" if ir else "Not Detected",
            "proximity": "Detected" if proximity else "Not Detected",
            "type": waste_type,
            "status": status,
        })
    return history


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
        self.history = generate_waste_history(140)
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
            "aws": "Connected",
        }
        self.live = self._make_live_reading()

    def _make_live_reading(self):
        metal = random.random() < 0.25
        moisture = round(random.uniform(20, 60), 1)
        ir = random.random() < 0.6
        proximity = random.random() < 0.85
        return {
            "metal": metal,
            "moisture": moisture,
            "ir": ir,
            "proximity": proximity,
            "servo": random.choice(["Idle", "Sorting", "Returning"]),
            "camera": "Online",
            "cloud": "Connected",
            "timestamp": iso_now(),
        }

    def tick(self):
        """Advance the simulated live sensor state by one step and log a
        waste record occasionally, mimicking a real detection event."""
        self.live = self._make_live_reading()

        if random.random() < 0.35:
            waste_type = _classify(self.live["metal"], self.live["moisture"], self.live["ir"])
            record = {
                "id": self.history[0]["id"] + 1 if self.history else 1,
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "timestamp": self.live["timestamp"],
                "metal": self.live["metal"],
                "moisture": self.live["moisture"],
                "ir": "Detected" if self.live["ir"] else "Not Detected",
                "proximity": "Detected" if self.live["proximity"] else "Not Detected",
                "type": waste_type,
                "status": "Sorted" if random.random() < 0.93 else "Rejected",
            }
            self.history.insert(0, record)
            return record
        return None

    def dashboard_summary(self):
        metal = sum(r["metal"] for r in self.history if r["type"] == "Metal") or 32
        wet_count = sum(1 for r in self.history if r["type"] == "Wet")
        dry_count = sum(1 for r in self.history if r["type"] == "Dry")
        metal_count = sum(1 for r in self.history if r["type"] == "Metal")

        metal_kg = round(metal_count * 0.9, 1) or 32
        wet_kg = round(wet_count * 1.1, 1) or 61
        dry_kg = round(dry_count * 0.85, 1) or 52
        total = round(metal_kg + wet_kg + dry_kg, 1)
        avg_moisture = round(
            sum(r["moisture"] for r in self.history) / len(self.history), 1
        ) if self.history else 35

        return {
            "totalWaste": total,
            "metalWaste": metal_kg,
            "wetWaste": wet_kg,
            "dryWaste": dry_kg,
            "avgMoisture": avg_moisture,
            "systemStatus": "Healthy",
            "awsStatus": self.device_status["aws"],
            "esp32Status": self.device_status["esp32"],
        }

    def analytics(self):
        metal_count = sum(1 for r in self.history if r["type"] == "Metal")
        wet_count = sum(1 for r in self.history if r["type"] == "Wet")
        dry_count = sum(1 for r in self.history if r["type"] == "Dry")
        total = max(metal_count + wet_count + dry_count, 1)
        return {
            "distribution": {
                "metal": round(metal_count / total * 100, 1),
                "wet": round(wet_count / total * 100, 1),
                "dry": round(dry_count / total * 100, 1),
            },
            "dailyCollection": self.daily_collection,
            "weeklyTrend": self.weekly_trend,
        }


store = Store()
