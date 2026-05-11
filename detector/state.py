from collections import defaultdict, deque
import threading
import time
import json
import os

# =========================
# TIME CONFIG
# =========================
WINDOW = 10

# =========================
# TRAFFIC WINDOWS
# =========================
ip_windows = defaultdict(deque)
global_window = deque()

ip_errors = defaultdict(int)
ip_requests = defaultdict(int)

# =========================
# SECURITY STATE
# =========================
offenses = defaultdict(int)
banned_ips = {}

# =========================
# BASELINE SYSTEM
# =========================
hourly_baselines = {
    hour: deque(maxlen=1800)
    for hour in range(24)
}

current_mean = 0.0
current_std = 0.0

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
