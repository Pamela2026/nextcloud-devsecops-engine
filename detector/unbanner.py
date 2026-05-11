import time
import state
from blocker import unblock_ip
from notifier import send_slack_alert

def unban_worker():

    print("[UNBAN] Worker started")

    while True:

        now = time.time()
        to_remove = []

        for ip, data in state.banned_ips.items():

            expires = data.get("expires", 0)

            # permanent ban
            if expires == float('inf'):
                continue

            if now >= expires:

                print(f"[UNBAN] Releasing {ip}")

                unblock_ip(ip)

                send_slack_alert(f"UNBAN: {ip} released")

                to_remove.append(ip)

        for ip in to_remove:
            del state.banned_ips[ip]

        time.sleep(5)
