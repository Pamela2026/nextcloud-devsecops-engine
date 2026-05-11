import statistics
import time
import state

def baseline_worker():

    print("[BASELINE] Worker started")

    while True:

        current_hour = time.localtime().tm_hour

        with state.lock:

            # =========================
            # GET CURRENT RPS
            # =========================
            current_rps = len(state.global_window)

            # =========================
            # STORE IN HOURLY BUCKET
            # =========================
            state.hourly_baselines[current_hour].append(current_rps)

            baseline_data = state.hourly_baselines[current_hour]

            # =========================
            # NOT ENOUGH DATA YET
            # =========================
            if len(baseline_data) < 30:
                time.sleep(60)
                continue

            # =========================
            # COMPUTE MEAN + STD
            # =========================
            try:
                mean_val = statistics.mean(baseline_data)
            except:
                mean_val = 1

            try:
                std_val = statistics.stdev(baseline_data)
            except:
                std_val = 1

            # =========================
            # SAFETY CLAMPING
            # =========================
            mean_val = max(mean_val, 1)
            std_val = max(std_val, 0.1)

            # =========================
            # STORE PER-HOUR STATS
            # =========================
            state.current_mean = mean_val
            state.current_std = std_val

            print(f"[BASELINE] hour={current_hour} mean={mean_val:.2f} std={std_val:.2f}")

            # =========================
            # AUDIT LOG
            # =========================
            with open("audit.log", "a") as f:
                f.write(
                    f"[{time.time()}] BASELINE "
                    f"hour={current_hour} "
                    f"mean={mean_val:.2f} "
                    f"std={std_val:.2f}\n"
                )

        time.sleep(60)
