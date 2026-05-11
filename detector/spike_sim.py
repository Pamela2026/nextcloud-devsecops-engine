import time
import threading
import random

ATTACK_IP = "203.0.113.99"  # reserved safe test IP (RFC 5737)

def normal_noise(logs):
    while True:
        ip = f"10.0.0.{random.randint(1, 50)}"
        logs.put((ip, time.time()))
        time.sleep(0.2)

def spike_attack(logs):
    # concentrated burst → guaranteed detection
    for _ in range(500):
        logs.put((ATTACK_IP, time.time()))
        time.sleep(0.005)

def run_simulator(logs):
    threading.Thread(target=normal_noise, args=(logs,), daemon=True).start()

    while True:
        time.sleep(8)   # frequent attack cycles
        print("[SIM] 🔥 SPIKE ATTACK TRIGGERED")
        spike_attack(logs)
