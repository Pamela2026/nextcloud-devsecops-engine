from collections import defaultdict, deque
import threading
import time
import json
import os
import yaml

# =========================
# LOAD CONFIG
# =========================
with open("config.yaml", "r") as f:
    state_config = yaml.safe_load(f)

# =========================
# TIME CONFIG
# =========================
WINDOW = 60  # 60-second sliding window for rate calculation

# =========================
# TRAFFIC WINDOWS
# =========================
ip_windows = defaultdict(deque)  # {ip: deque of timestamps}
global_window = deque()           # deque of all request timestamps

ip_errors = defaultdict(int)      # {ip: count of 4xx/5xx}
ip_requests = defaultdict(int)    # {ip: total requests}

# =========================
# SECURITY STATE
# =========================
offenses = defaultdict(int)       # {ip: offense count for escalation}
banned_ips = {}                   # {ip: {expires: timestamp or None}}

# =========================
# BASELINE SYSTEM (per hour)
# =========================
hourly_baselines = {
    hour: deque(maxlen=1800)  # 30 min * 60 sec = 1800 samples max
    for hour in range(24)
}

# Store per-hour statistics
current_mean = {hour: None for hour in range(24)}
current_std = {hour: None for hour in range(24)}

# =========================
# SYNCHRONIZATION
# =========================
lock = threading.Lock()

start_time = time.time()

STATE_FILE = "state_store.json"


# =========================
# SAFE SAVE (ATOMIC WRITE)
# =========================
def save_state():
    tmp = "state_store.tmp"

    with lock:
        with open(tmp, "w") as f:
            json.dump({
                "offenses": dict(offenses),
                "banned_ips": banned_ips
            }, f)

    os.replace(tmp, STATE_FILE)


# =========================
# SAFE LOAD (ROBUST)
# =========================
def load_state():
    try:
        if not os.path.exists(STATE_FILE):
            print("[STATE] No previous state found")
            return

        with open(STATE_FILE, "r") as f:
            content = f.read().strip()

            if not content:
                print("[STATE] Empty state file, skipping load")
                return

            data = json.loads(content)

            with lock:
                offenses.update(data.get("offenses", {}))
                banned_ips.update(data.get("banned_ips", {}))

        print("[STATE] Restored previous state")

    except json.JSONDecodeError:
        print("[STATE] Corrupted state file, ignoring")

    except Exception as e:
        print(f"[STATE] Load error: {e}")
