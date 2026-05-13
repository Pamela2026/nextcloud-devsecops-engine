import time
import math
import traceback
import yaml
import state

from blocker import block_ip
from notifier import send_slack_alert

# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

Z_SCORE_THRESHOLD = config.get("thresholds", {}).get("z_score", 3.0)
SPIKE_MULTIPLIER = config.get("thresholds", {}).get("spike_multiplier", 5)
BAN_DURATIONS = config.get("ban_durations", [600, 1800, 7200])  # 10m, 30m, 2h


def detector_worker(logs):
    """
    Main detector worker. Processes each log entry and:
    1. Updates sliding windows (per-IP and global)
    2. Calculates current rates
    3. Applies anomaly detection (z-score or spike multiplier)
    4. Handles error surge adaptation
    5. Triggers blocking and alerts
    6. Logs audit trail
    """
    
    print("[DETECTOR] Worker started")
    
    while True:
        try:
            log = logs.get()
            
            print(f"[DETECTOR] Log received: {log}")
            
            if isinstance(log, dict):
                ip = log.get("source_ip", "unknown")
                status = log.get("status", 200)
                path = log.get("path", "/")
            elif isinstance(log, tuple):
                ip = log[0] if len(log) > 0 else "unknown"
                status = 200
                path = "/"
            else:
                ip = str(log)
                status = 200
                path = "/"
            
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
                # UPDATE SLIDING WINDOWS (60-second)
                # =========================
                state.ip_windows[ip].append(now)
                state.global_window.append(now)
                
                # =========================
                # EVICT OLD ENTRIES (outside 60s window)
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
                # TRACK ERROR RATES
                # =========================
                state.ip_requests[ip] += 1
                if status >= 400:
                    state.ip_errors[ip] += 1
                
                # =========================
                # CURRENT RATES
                # =========================
                ip_rate = len(state.ip_windows[ip])
                global_rate = len(state.global_window)
                
                current_hour = time.localtime().tm_hour
                mean = state.current_mean[current_hour]
                std = state.current_std[current_hour]
                baseline_ready = mean is not None and std is not None

                if not baseline_ready:
                    print(
                        f"[DETECTOR] Baseline not ready for hour={current_hour}; "
                        f"skipping anomaly detection"
                    )
                    continue

                std = max(std, 0.1)  # Floor std to prevent division issues
                
                # =========================
                # Z-SCORE CALCULATION
                # =========================
                if mean > 0:
                    z_score = (ip_rate - mean) / std
                else:
                    z_score = 0
                
                print(
                    f"[DETECTOR] ip={ip} "
                    f"rate={ip_rate} "
                    f"mean={mean:.2f} "
                    f"std={std:.2f} "
                    f"z={z_score:.2f}"
                )
                
                # =========================
                # ERROR RATE & ADAPTIVE THRESHOLD
                # =========================
                baseline_error_rate = 0.01  # 1% baseline error rate
                error_rate = 0
                
                if state.ip_requests[ip] > 0:
                    error_rate = (
                        state.ip_errors[ip]
                        / state.ip_requests[ip]
                    )
                
                # If error rate is 3x baseline, tighten detection thresholds
                adaptive_threshold = Z_SCORE_THRESHOLD
                if error_rate > (3 * baseline_error_rate):
                    adaptive_threshold = max(2.0, Z_SCORE_THRESHOLD - 0.5)
                    print(
                        f"[DETECTOR] ADAPTIVE: error_rate={error_rate:.3f} "
                        f"-> threshold lowered to {adaptive_threshold}"
                    )
                
                # =========================
                # ANOMALY DETECTION
                # =========================
                # Fires if EITHER condition is true
                anomalous = (
                    z_score > adaptive_threshold
                    or ip_rate > (SPIKE_MULTIPLIER * mean)
                )
                
                if anomalous and ip not in state.banned_ips:
                    print(f"[DETECTOR] ANOMALY DETECTED for {ip}")
                    
                    state.offenses[ip] += 1
                    offense_count = state.offenses[ip]
                    
                    # =========================
                    # BACKOFF ESCALATION
                    # =========================
                    if offense_count <= len(BAN_DURATIONS):
                        duration = BAN_DURATIONS[offense_count - 1]
                    else:
                        duration = None  # Permanent ban after all durations exhausted
                    
                    # =========================
                    # APPLY BLOCK
                    # =========================
                    block_ip(ip, duration)
                    
                    # =========================
                    # TRACK BAN IN STATE
                    # =========================
                    if duration:
                        state.banned_ips[ip] = {
                            "expires": now + duration,
                            "offense_count": offense_count,
                            "reason": "z_score" if z_score > adaptive_threshold else "spike"
                        }
                    else:
                        state.banned_ips[ip] = {
                            "expires": float('inf'),  # Permanent
                            "offense_count": offense_count,
                            "reason": "permanent"
                        }
                    
                    # =========================
                    # SLACK ALERT
                    # =========================
                    condition_fired = (
                        "z_score" if z_score > adaptive_threshold else "spike_multiplier"
                    )
                    
                    alert_message = (
                        f"🚨 **HNG ANOMALY DETECTED**\n\n"
                        f"**IP:** `{ip}`\n"
                        f"**Condition:** {condition_fired}\n"
                        f"**Rate:** {ip_rate} req/s\n"
                        f"**Baseline Mean:** {mean:.2f} req/s\n"
                        f"**Stddev:** {std:.2f}\n"
                        f"**Z-Score:** {z_score:.2f}\n"
                        f"**Offense Count:** {offense_count}\n"
                        f"**Ban Duration:** {duration}s" + 
                        (" (Permanent)" if duration is None else "") + 
                        f"\n**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                    send_slack_alert(alert_message)
                    
                    # =========================
                    # AUDIT LOG (STRUCTURED)
                    # =========================
                    with open("audit.log", "a") as f:
                        f.write(
                            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"BAN | ip={ip} | "
                            f"condition={condition_fired} | "
                            f"rate={ip_rate} | "
                            f"baseline={mean:.2f} | "
                            f"duration={duration}\n"
                        )
        
        except Exception:
            print("[DETECTOR ERROR]")
            traceback.print_exc()
            time.sleep(1)
