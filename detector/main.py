# =========================
# ASYNC WEB SERVER FOR DASHBOARD
# =========================
import uvicorn
from threading import Thread


def run_dashboard():
    """
    Start FastAPI/Uvicorn dashboard server on configured port.
    """
    from dashboard import app
    config = yaml.safe_load(open("config.yaml"))
    port = config.get("dashboard_port", 8000)
    print(f"[MAIN] Starting dashboard on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


# =========================
# MAIN EXECUTION
# =========================
if __name__ == "__main__":
    from queue import Queue
    from threading import Thread
    import time
    import signal
    import sys
    import yaml

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
    # SHARED EVENT BUS
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

    # attack simulator (for testing)
    start_thread("simulator", run_simulator, args=(logs,))

    # =========================
    # SERVICES
    # =========================
    start_thread("state_saver", state_saver)
    
    # Run dashboard in main thread (blocking)
    print("[MAIN] Core engine fully started")
    try:
        run_dashboard()
    except KeyboardInterrupt:
        print("\n[MAIN] Graceful shutdown initiated")
        state.save_state()
        sys.exit(0)

