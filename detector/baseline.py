import statistics
import time
import state
from notifier import send_slack_alert


def baseline_worker():
    """
    Baseline calculation worker.
    
    Every 60 seconds:
    1. Samples current global RPS (requests in last 60 seconds)
    2. Adds to hourly bucket for current hour
    3. Once 30 samples (30 min window), calculates mean + stddev
    4. Stores per-hour statistics in state.current_mean and state.current_std
    5. Prefers current hour baseline; falls back to 24-hour average if needed
    """
    
    print("[BASELINE] Worker started")
    
    while True:
        try:
            current_hour = time.localtime().tm_hour
            
            with state.lock:
                # =========================
                # SAMPLE CURRENT GLOBAL RPS
                # =========================
                current_rps = len(state.global_window)
                
                # =========================
                # STORE IN HOURLY BUCKET
                # =========================
                state.hourly_baselines[current_hour].append(current_rps)
                
                baseline_data = state.hourly_baselines[current_hour]
                
                # =========================
                # NOT ENOUGH DATA YET (< 30 min)
                # =========================
                if len(baseline_data) < 30:
                    print(f"[BASELINE] hour={current_hour} samples={len(baseline_data)}/30 (warming up)")
                    # Don't update statistics yet
                else:
                    # =========================
                    # COMPUTE MEAN + STD FOR CURRENT HOUR
                    # =========================
                    try:
                        mean_val = statistics.mean(baseline_data)
                        std_val = statistics.stdev(baseline_data) if len(baseline_data) > 1 else 0.1
                    except (ValueError, statistics.StatisticsError):
                        mean_val = 1.0
                        std_val = 0.1
                    
                    # =========================
                    # SAFETY FLOOR (minimum baseline)
                    # =========================
                    mean_val = max(mean_val, 1.0)
                    std_val = max(std_val, 0.1)
                    
                    # =========================
                    # STORE PER-HOUR STATS
                    # =========================
                    state.current_mean[current_hour] = mean_val
                    state.current_std[current_hour] = std_val
                    
                    print(
                        f"[BASELINE] hour={current_hour} "
                        f"samples={len(baseline_data)} "
                        f"mean={mean_val:.2f} "
                        f"std={std_val:.2f}"
                    )
                    
                    # =========================
                    # AUDIT LOG
                    # =========================
                    with open("audit.log", "a") as f:
                        f.write(
                            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"BASELINE | hour={current_hour} | "
                            f"mean={mean_val:.2f} | "
                            f"std={std_val:.2f}\n"
                        )
                    
                    # =========================
                    # SLACK ALERT
                    # =========================
                    alert_message = (
                        f"📊 **BASELINE UPDATED**\n\n"
                        f"**Hour:** {current_hour}:00\n"
                        f"**Samples:** {len(baseline_data)}\n"
                        f"**Mean RPS:** {mean_val:.2f} req/s\n"
                        f"**Stddev:** {std_val:.2f}\n"
                        f"**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    send_slack_alert(alert_message)
        
        except Exception as e:
            print(f"[BASELINE ERROR] {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(60)
