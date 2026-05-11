from queue import Queue
from threading import Thread
import time
import signal
import sys

import state

from spike_sim import run_simulator
from monitor import tail_logs
from detector import detector_worker
from baseline import baseline_worker
from unbanner import unban_worker


# =========================
# LOAD STATE
# =========================
state.load_state()

print("[MAIN] Starting anomaly detection system")


# =========================
# SHARED EVENT BUS (FIXED)
# =========================
logs = Queue()


# =========================
# THREAD HELPER
# =========================
def start_thread(name, target, args=()):
    print(f"[MAIN] Starting {name} thread")
    t = Thread(target=target, args=args, daemon=True)
    t.start()
    return t


# =========================
# ADAPTER: tail_logs -> Queue feeder
# =========================
def log_feeder():
    """
    Converts tail_logs() generator into Queue stream
    so detector_worker can safely consume it.
    """
    stream = tail_logs()
    for item in stream:
        logs.put(item)


# =========================
# SAFE DASHBOARD LOOP
# =========================
def safe_dashboard():
    while True:
        try:
            print("[DASHBOARD] Starting UI server")
        except Exception as e:
            print(f"[DASHBOARD ERROR] {e}")
            time.sleep(5)


# =========================
# STATE SAVER LOOP
# =========================
def state_saver():
    while True:
        time.sleep(30)
        try:
            state.save_state()
            print("[STATE] Auto-saved")
        except Exception as e:
            print(f"[STATE ERROR] {e}")


# =========================
# WARMUP
# =========================
print("[MAIN] Warming up baseline system (10s)")
time.sleep(10)


# =========================
# START CORE SYSTEM
# =========================
start_thread("baseline", baseline_worker)
start_thread("unban", unban_worker)

# feed logs into queue
start_thread("log_feeder", log_feeder)

# detector consumes queue
start_thread("detector", detector_worker, args=(logs,))

# attack simulator
start_thread("simulator", run_simulator, args=(logs,))


# =========================
# SERVICES
# =========================
start_thread("dashboard", safe_dashboard)
start_thread("state_saver", state_saver)


print("[MAIN] Core engine fully started")


# =========================
# SHUTDOWN HANDLER
# =========================
def shutdown(sig, frame):
    print("\n[MAIN] Graceful shutdown initiated")
    try:
        state.save_state()
    except Exception as e:
        print(f"[SHUTDOWN ERROR] {e}")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# =========================
# KEEP ALIVE
# =========================
while True:
    time.sleep(60)
