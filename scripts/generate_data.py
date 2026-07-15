"""
generate_data.py
CIPHER - Synthetic behavioral login data generator
Produces 5 CSVs matching the warehouse schema, with 3 planted incidents.
"""

import os
import random
import csv
from datetime import datetime, timedelta

random.seed(42)  # reproducible runs

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
NUM_USERS = 40
SIM_DAYS = 120          # ~4 months
START_DATE = datetime(2026, 3, 1)
END_DATE = START_DATE + timedelta(days=SIM_DAYS)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -------------------------------------------------------------------
# DIMENSION DATA
# -------------------------------------------------------------------

FIRST_NAMES = ["James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda",
               "David","Elizabeth","William","Barbara","Richard","Susan","Joseph","Jessica",
               "Thomas","Sarah","Charles","Karen","Daniel","Nancy","Matthew","Lisa",
               "Anthony","Betty","Mark","Margaret","Paul","Sandra","Steven","Ashley",
               "Andrew","Kimberly","Kenneth","Emily","George","Donna","Joshua","Michelle"]

DEPARTMENTS = ["Engineering","Finance","HR","Sales","Marketing","Legal","IT","Operations"]
ROLES = ["Analyst","Manager","Engineer","Specialist","Director","Associate"]

DEVICE_TYPES = [("laptop","Windows"), ("laptop","macOS"), ("mobile","iOS"),
                ("mobile","Android"), ("tablet","iOS")]

# (city, country, lat, lon)
LOCATIONS = [
    ("New York","USA",40.7128,-74.0060),
    ("Chicago","USA",41.8781,-87.6298),
    ("San Francisco","USA",37.7749,-122.4194),
    ("London","UK",51.5074,-0.1278),
    ("Berlin","Germany",52.5200,13.4050),
    ("Toronto","Canada",43.6532,-79.3832),
    ("Singapore","Singapore",1.3521,103.8198),
    ("Sydney","Australia",-33.8688,151.2093),
    ("Mumbai","India",19.0760,72.8777),
    ("Tokyo","Japan",35.6762,139.6503),
    ("Sao Paulo","Brazil",-23.5505,-46.6333),
    ("Dubai","UAE",25.2048,55.2708),
]

APPLICATIONS = [
    ("EmailSuite","low"),
    ("Intranet","low"),
    ("HR_Portal","medium"),
    ("Payroll_System","high"),
    ("CRM","medium"),
    ("Finance_Ledger","high"),
    ("SourceCode_Repo","high"),
    ("Admin_Console","high"),
    ("VPN_Gateway","medium"),
    ("Shared_Drive","low"),
]

# -------------------------------------------------------------------
# BUILD DIMENSION TABLES
# -------------------------------------------------------------------

users = []
for i in range(1, NUM_USERS + 1):
    fn = random.choice(FIRST_NAMES)
    username = f"{fn.lower()}{i}"
    users.append({
        "user_id": i,
        "username": username,
        "full_name": f"{fn} {random.choice(['Smith','Lee','Brown','Garcia','Kim','Patel','Nguyen','Muller'])}",
        "department": random.choice(DEPARTMENTS),
        "role": random.choice(ROLES),
        "created_at": (START_DATE - timedelta(days=random.randint(30,400))).strftime("%Y-%m-%d %H:%M:%S")
    })

devices = []
device_id_counter = 1
# each user gets 1-2 "home" devices they normally use
user_home_devices = {}
for u in users:
    n_devices = random.choice([1,1,1,2])
    dev_ids = []
    for _ in range(n_devices):
        dtype, os_name = random.choice(DEVICE_TYPES)
        devices.append({
            "device_id": device_id_counter,
            "device_fingerprint": f"DEV-{device_id_counter:05d}-{random.randint(1000,9999)}",
            "device_type": dtype,
            "os": os_name,
            "first_seen": (START_DATE - timedelta(days=random.randint(1,300))).strftime("%Y-%m-%d %H:%M:%S")
        })
        dev_ids.append(device_id_counter)
        device_id_counter += 1
    user_home_devices[u["user_id"]] = dev_ids

locations = []
for i, (city, country, lat, lon) in enumerate(LOCATIONS, start=1):
    locations.append({
        "location_id": i, "city": city, "country": country,
        "latitude": lat, "longitude": lon
    })

applications = []
for i, (name, sens) in enumerate(APPLICATIONS, start=1):
    applications.append({
        "application_id": i, "app_name": name, "sensitivity_level": sens
    })

# each user gets 1-2 "home" locations they normally log in from
user_home_locations = {}
for u in users:
    n_locs = random.choice([1,1,2])
    user_home_locations[u["user_id"]] = random.sample(range(1, len(locations)+1), n_locs)

# -------------------------------------------------------------------
# BUILD NORMAL LOGIN ACTIVITY (~4 months)
# -------------------------------------------------------------------

events = []
event_id_counter = 1

def add_event(user_id, device_id, location_id, application_id, ts, status):
    global event_id_counter
    events.append({
        "event_id": event_id_counter,
        "user_id": user_id,
        "device_id": device_id,
        "location_id": location_id,
        "application_id": application_id,
        "event_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "login_status": status,
        "ip_address": f"{random.randint(10,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    })
    event_id_counter += 1

for u in users:
    uid = u["user_id"]
    home_devices = user_home_devices[uid]
    home_locations = user_home_locations[uid]

    current_day = START_DATE
    while current_day < END_DATE:
        if current_day.weekday() < 5 and random.random() < 0.85:  # weekday, usually logs in
            n_logins = random.randint(1,4)
            for _ in range(n_logins):
                hour = random.randint(8,18)
                minute = random.randint(0,59)
                ts = current_day.replace(hour=hour, minute=minute)
                device_id = random.choice(home_devices)
                location_id = random.choice(home_locations)
                app_id = random.choice([a["application_id"] for a in applications if a["sensitivity_level"]=="low"] +
                                        [a["application_id"] for a in applications if a["sensitivity_level"]=="medium"])
                status = "success" if random.random() > 0.03 else "failure"
                add_event(uid, device_id, location_id, app_id, ts, status)
        current_day += timedelta(days=1)

# -------------------------------------------------------------------
# INCIDENT 1 — CREDENTIAL COMPROMISE
# -------------------------------------------------------------------

incident1_user = users[5]["user_id"]
incident1_start = START_DATE + timedelta(days=60)

new_device_id = device_id_counter
devices.append({
    "device_id": new_device_id,
    "device_fingerprint": f"DEV-{new_device_id:05d}-ATTACK",
    "device_type": "laptop",
    "os": "Linux",
    "first_seen": incident1_start.strftime("%Y-%m-%d %H:%M:%S")
})
device_id_counter += 1

candidate_locs = [l for l in range(1,len(locations)+1) if l not in user_home_locations[incident1_user]]
new_location_id = random.choice(candidate_locs)

for day_offset in range(3):
    day = incident1_start + timedelta(days=day_offset)
    n_attempts = random.randint(6,10)
    for _ in range(n_attempts):
        hour = random.randint(0,23)
        ts = day.replace(hour=hour, minute=random.randint(0,59))
        add_event(incident1_user, new_device_id, new_location_id, 1, ts, "failure")

breach_ts = (incident1_start + timedelta(days=3)).replace(hour=3, minute=random.randint(0,59))
add_event(incident1_user, new_device_id, new_location_id, 1, breach_ts, "success")

sensitive_app_id = next(a["application_id"] for a in applications if a["app_name"] == "Finance_Ledger")
pivot_ts = breach_ts + timedelta(minutes=random.randint(3,15))
add_event(incident1_user, new_device_id, new_location_id, sensitive_app_id, pivot_ts, "success")

# -------------------------------------------------------------------
# INCIDENT 2 — IMPOSSIBLE TRAVEL
# -------------------------------------------------------------------

incident2_user = users[15]["user_id"]
incident2_day = START_DATE + timedelta(days=80)

london_id = next(l["location_id"] for l in locations if l["city"] == "London")
singapore_id = next(l["location_id"] for l in locations if l["city"] == "Singapore")

t1 = incident2_day.replace(hour=14, minute=0)
t2 = t1 + timedelta(minutes=15)

dev_for_incident2 = user_home_devices[incident2_user][0]

add_event(incident2_user, dev_for_incident2, london_id, 2, t1, "success")
add_event(incident2_user, dev_for_incident2, singapore_id, 2, t2, "success")

# -------------------------------------------------------------------
# INCIDENT 3 — DORMANT ACCOUNT REACTIVATION
# -------------------------------------------------------------------

incident3_user = users[25]["user_id"]

dormant_cutoff = START_DATE + timedelta(days=20)
events = [e for e in events if not (
    e["user_id"] == incident3_user and
    datetime.strptime(e["event_timestamp"], "%Y-%m-%d %H:%M:%S") > dormant_cutoff
)]

reactivation_ts = START_DATE + timedelta(days=110, hours=13, minutes=22)
dev_for_incident3 = user_home_devices[incident3_user][0]
loc_for_incident3 = user_home_locations[incident3_user][0]
admin_app_id = next(a["application_id"] for a in applications if a["app_name"] == "Admin_Console")

add_event(incident3_user, dev_for_incident3, loc_for_incident3, admin_app_id, reactivation_ts, "success")

# -------------------------------------------------------------------
# WRITE CSVs
# -------------------------------------------------------------------

def write_csv(filename, rows, fieldnames):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {path}")

write_csv("dim_user.csv", users, ["user_id","username","full_name","department","role","created_at"])
write_csv("dim_device.csv", devices, ["device_id","device_fingerprint","device_type","os","first_seen"])
write_csv("dim_location.csv", locations, ["location_id","city","country","latitude","longitude"])
write_csv("dim_application.csv", applications, ["application_id","app_name","sensitivity_level"])

events.sort(key=lambda e: (e["user_id"], e["event_timestamp"]))
for idx, e in enumerate(events, start=1):
    e["event_id"] = idx

write_csv("fact_login_events.csv", events,
          ["event_id","user_id","device_id","location_id","application_id",
           "event_timestamp","login_status","ip_address"])

print("\nDone. Planted incidents:")
print(f"  Incident 1 (credential compromise): user_id={incident1_user}")
print(f"  Incident 2 (impossible travel):      user_id={incident2_user}")
print(f"  Incident 3 (dormant reactivation):    user_id={incident3_user}")