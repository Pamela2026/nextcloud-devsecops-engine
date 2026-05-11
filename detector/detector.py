import time
import math
import traceback
import state

from blocker import block_ip
from notifier import send_slack_alert


def detector_worker(logs):

    print("[DETECTOR] Worker started")

    while True:

        try:

            log = logs.get()

            print(f"[DETECTOR] Log received: {log}")

            ip = log["source_ip"]

            # =========================
            # SKIP INTERNAL IPS
            # =========================
            if (
                ip.startswith("127.")
                or ip.startswith("10.")
                or ip.startswith("172.")
                or ip.startswith("192.168.")
            ):
                continue

            now = time.time()

            with state.lock:

                # =========================
                # UPDATE WINDOWS
                # =========================
                state.ip_windows[ip].append(now)

                state.global_window.append(now)

                # =========================
                # EVICT OLD ENTRIES
                # =========================
                while (
                    state.ip_windows[ip]
                    and now - state.ip_windows[ip][0] > state.WINDOW
                ):
                    state.ip_windows[ip].popleft()

                while (
                    state.global_window
                    and now - state.global_window[0] > state.WINDOW
                ):
                    state.global_window.popleft()

                # =========================
                # TRACK REQUESTS
                # =========================
                state.ip_requests[ip] += 1

                if log["status"] >= 400:
                    state.ip_errors[ip] += 1

                # =========================
                # CURRENT RATES
                # =========================
                ip_rate = len(state.ip_windows[ip])

                global_rate = len(state.global_window)

                current_hour = time.localtime().tm_hour

                mean = state.current_mean[current_hour]

                std = state.current_std[current_hour]

                std = max(std, 0.1)

                # =========================
                # Z-SCORE
                # =========================
                z_score = (ip_rate - mean) / std

                print(
                    f"[DETECTOR] ip={ip} "
                    f"rate={ip_rate} "
                    f"mean={mean:.2f} "
                    f"std={std:.2f} "
                    f"z={z_score:.2f}"
                )

                # =========================
                # ERROR RATE
                # =========================
                error_rate = 0

                if state.ip_requests[ip] > 0:
                    error_rate = (
                        state.ip_errors[ip]
                        / state.ip_requests[ip]
                    )

                # =========================
                # ADAPTIVE THRESHOLD
                # =========================
                threshold = 3.0

                if error_rate > 0.3:
                    threshold = 2.0

                # =========================
                # DETECTION LOGIC
                # =========================
                anomalous = (
                    z_score > threshold
                    or ip_rate > (5 * mean)
                )

                if anomalous:

                    if ip not in state.banned_ips:

                        print(f"[BAN] Blocking IP {ip}")

                        state.offenses[ip] += 1

                        offense_count = state.offenses[ip]

                        # =========================
                        # BACKOFF ESCALATION
                        # =========================
                        if offense_count == 1:
                            duration = 600

                        elif offense_count == 2:
                            duration = 1800

                        elif offense_count == 3:
                            duration = 7200

                        else:
                            duration = None

                        # =========================
                        # APPLY BLOCK
                        # =========================
                        block_ip(ip, duration)

                        # =========================
                        # TRACK BAN
                        # =========================
                        if duration:

                            state.banned_ips[ip] = {
                                "expires": now + duration
                            }

                        else:

                            state.banned_ips[ip] = {
                                "expires": None
                            }

                        # =========================
                        # SLACK ALERT
                        # =========================
                        send_slack_alert(
                            f"""
🚨 HNG ANOMALY DETECTED

IP: {ip}

Rate: {ip_rate}

Mean: {mean:.2f}

Stddev: {std:.2f}

Z-Score: {z_score:.2f}

Duration: {duration}
"""
                        )

                        # =========================
                        # AUDIT LOG
                        # =========================
                        with open("audit.log", "a") as f:

                            f.write(
                                f"[{time.time()}] "
                                f"BAN {ip} | "
                                f"rate={ip_rate} | "
                                f"baseline={mean:.2f} | "
                                f"duration={duration}\n"
                            )

        except Exception:

            print("[DETECTOR ERROR]")

            traceback.print_exc()

            time.sleep(1)
