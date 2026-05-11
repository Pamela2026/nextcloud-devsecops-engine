import json
import time
import os
import state

LOG_FILE = "/logs/hng-access.log"

def tail_logs():

    print(f"[MONITOR] Waiting for log file: {LOG_FILE}")

    while not os.path.exists(LOG_FILE):
        time.sleep(1)

    print("[MONITOR] Log file detected")

    with open(LOG_FILE, "r") as f:

        f.seek(0, 2)

        while True:

            line = f.readline()

            if not line:
                time.sleep(0.1)
                continue

            try:

                parsed = json.loads(line)

                print(f"[MONITOR] Parsed log: {parsed}")

                yield parsed

            except Exception as e:

                print(f"[MONITOR ERROR] {e}")
