# HNG DevSecOps Engine - Architecture Documentation

## System Overview

The anomaly detection engine is a multithreaded Python daemon that monitors Nextcloud traffic in real-time and automatically blocks malicious IPs based on statistical anomalies.

### Core Design Principles

1. **Real-Time Processing** - Every log line processed within milliseconds
2. **Stateful Baseline** - 30-minute rolling window capturing diurnal patterns
3. **Automatic Response** - Sub-10 second ban latency
4. **Graceful Degradation** - Continues operating even with incomplete baselines
5. **Auditability** - Every action logged with structured timestamps

---

## Thread Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    main.py (Orchestrator)                    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
├─► baseline_worker() ──────────► [Baseline Thread]           │
│   • Samples global RPS every 60s                             │
│   • Maintains hourly deques (1800 samples each)              │
│   • Recalculates mean/stddev                                 │
│                                                              │
├─► log_feeder() ─────────────────► [Log Feed Thread]         │
│   • Tails /logs/hng-access.log                               │
│   • Parses JSON lines                                        │
│   • Queues for detector                                      │
│                                                              │
├─► detector_worker() ────────────► [Detection Thread]        │
│   • Consumes log queue                                       │
│   • Updates sliding windows                                  │
│   • Applies z-score & spike logic                            │
│   • Triggers block_ip() on anomaly                           │
│                                                              │
├─► unban_worker() ────────────────► [Unban Thread]           │
│   • Checks expiration times (every 10s)                      │
│   • Calls unblock_ip() when expired                          │
│   • Sends unban Slack alerts                                 │
│                                                              │
├─► state_saver() ─────────────────► [State Persistence]     │
│   • Saves banned_ips & offenses (every 30s)                 │
│   • Atomic JSON write (tmp file + rename)                    │
│                                                              │
├─► run_dashboard() [BLOCKING] ────► [FastAPI/Uvicorn]       │
│   • Serves /metrics endpoint                                 │
│   • Serves HTML dashboard at /                               │
│   • Runs on port 8000                                        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

All daemon threads except main() run as `daemon=True` so the process can exit cleanly.

---

## Data Flow Diagram

```
┌─────────────────┐
│  HTTP Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│   Nginx Reverse Proxy   │
│   (JSON Access Log)     │
└────────┬────────────────┘
         │
         ▼ /var/log/nginx/hng-access.log
┌─────────────────────────┐
│   Named Docker Volume   │
│    HNG-nginx-logs       │
└────────┬────────────────┘
         │
         ▼ (read-only mount)
┌──────────────────────────────────────────────────────────┐
│         Detector Container (Linux host namespace)        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ monitor.py: tail_logs() generator                  │ │
│  │ └─► Streams parsed JSON log entries                │ │
│  └────────────────┬─────────────────────────────────┘ │
│                   │                                    │
│  ┌────────────────▼──────────────────────────────────┐ │
│  │ main.py: log_feeder() thread                      │ │
│  │ └─► Pulls from generator, pushes to Queue         │ │
│  └────────────────┬─────────────────────────────────┘ │
│                   │                                    │
│                   ▼ (logs Queue)                       │
│  ┌────────────────────────────────────────────────────┐ │
│  │ detector.py: detector_worker() thread             │ │
│  │ ├─► Pop log from queue                            │ │
│  │ ├─► Update state.ip_windows[ip]                   │ │
│  │ ├─► Update state.global_window                    │ │
│  │ ├─► Evict old timestamps                          │ │
│  │ ├─► Calculate rates and z-scores                  │ │
│  │ ├─► Check anomaly conditions                      │ │
│  │ └─► If anomalous: block_ip() + notify Slack       │ │
│  └────────────┬─────────────────────┬────────────────┘ │
│               │                     │                   │
│               ▼                     ▼                   │
│  ┌──────────────────────┐  ┌──────────────────────┐   │
│  │ blocker.py           │  │ notifier.py          │   │
│  │ └─► iptables DROP    │  │ └─► Slack webhook    │   │
│  └──────────┬───────────┘  └──────────┬───────────┘   │
│             │                        │                │
│             ▼ (host iptables)        ▼ (Slack API)    │
│  ┌──────────────────────┐  ┌──────────────────────┐   │
│  │ [Host iptables rules]│  │ [Slack Workspace]    │   │
│  └──────────────────────┘  └──────────────────────┘   │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ baseline.py: baseline_worker() thread             │ │
│  │ └─► Sample global_window every 60s                │ │
│  │     └─► Store in hourly_baselines[hour]           │ │
│  │     └─► Recalc mean/stddev if 30+ samples        │ │
│  │     └─► Update current_mean/current_std            │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ unbanner.py: unban_worker() thread                │ │
│  │ └─► Poll banned_ips every 10s for expiration      │ │
│  │     └─► unblock_ip() when time reached            │ │
│  │     └─► Send unban Slack alerts                   │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ dashboard.py: FastAPI web server (Uvicorn)        │ │
│  │ ├─► GET /metrics → JSON current state             │ │
│  │ └─► GET / → HTML dashboard (auto-refresh 3s)      │ │
│  └────────────────┬─────────────────────────────────┘ │
│                   │                                    │
└───────────────────┼────────────────────────────────────┘
                    │
                    ▼ (Port 8000)
            [Dashboard Browser]
```

---

## State Management

### Thread-Safe Shared State (`state.py`)

```python
# All protected by state.lock (threading.RLock)

# Traffic tracking
ip_windows = defaultdict(deque)     # {ip: deque([ts1, ts2, ...])}
global_window = deque()             # [ts1, ts2, ts3, ...]

# Request/error counters
ip_requests = defaultdict(int)      # {ip: count}
ip_errors = defaultdict(int)        # {ip: count}

# Security state
offenses = defaultdict(int)         # {ip: escalation_level}
banned_ips = {}                     # {ip: {expires, offense_count, reason}}

# Baseline stats (per-hour)
hourly_baselines = {                # {hour: deque([rps1, rps2, ...])}
    hour: deque(maxlen=1800)
    for hour in range(24)
}
current_mean = {hour: 1.0 ...}      # {hour: mean}
current_std = {hour: 0.1 ...}       # {hour: stddev}
```

### State Persistence

```
state_store.json (saved every 30s via state_saver thread)

{
  "offenses": {
    "203.0.113.99": 2,
    "198.51.100.50": 1
  },
  "banned_ips": {
    "203.0.113.99": {
      "expires": 1715420400.5,
      "offense_count": 2,
      "reason": "z_score"
    }
  }
}
```

On daemon restart, `state.load_state()` restores ban history, so repeat offenders are immediately escalated.

---

## Sliding Window Mechanics

### Per-Request Flow

```
┌──────────────────────────────────────────────────┐
│ Log: {"source_ip": "203.0.113.99", ...}         │
└────────────────────┬─────────────────────────────┘
                     │
    ┌────────────────▼────────────────┐
    │ now = time.time()               │
    └────────────────┬────────────────┘
                     │
    ┌────────────────▼────────────────┐
    │ APPEND to ip_windows["203..."]  │  now
    │ APPEND to global_window         │  │
    └────────────────┬────────────────┘  │
                     │                    │
    ┌────────────────▼────────────────┐  │
    │ EVICT from ip_windows["203..."] │  │
    │ while (now - ts[0] > 60):       │  │
    │   popleft()                     │  │
    │                                 │  │
    │ EVICT from global_window        │  │
    │ while (now - ts[0] > 60):       │  │
    │   popleft()                     │  │
    └────────────────┬────────────────┘  │
                     │                    │
    ┌────────────────▼────────────────┐  │
    │ rate_ip = len(ip_windows[ip])   │  │
    │ rate_global = len(global_window)│  │
    │                                 │  │
    │ Current window holds all        │  │
    │ requests from:                  │  │
    │ (now - 60) to now              │  │
    └─────────────────────────────────┘  │
                                         now-60
```

### Example Timeline

```
Time (sec)  Event                          ip_windows["203..."]  global_window
───────────────────────────────────────────────────────────────────────────
0:00        Request from 203...           [0:00]               [0:00]
0:05        Request from 203...           [0:00, 0:05]         [0:00, 0:05]
0:10        Request from other IP         [0:00, 0:05]         [0:00, 0:05, 0:10]
0:30        Request from 203...           [0:00, 0:05, 0:30]   [0:00, 0:05, 0:10, 0:30]
1:00        Request from 203...           [0:00, 0:05, 0:30, 1:00]  [0:00, 0:05, 0:10, 0:30, 1:00]
1:05        Request from 203...           [0:05, 0:30, 1:00, 1:05]  [0:05, 0:10, 0:30, 1:00, 1:05]
            (0:00 evicted - outside 60s)
1:10        Request from 203...           [0:30, 1:00, 1:05, 1:10]  [0:10, 0:30, 1:00, 1:05, 1:10]
            (0:05 evicted - outside 60s)
```

---

## Baseline Learning Process

### Sample Accumulation

```
BASELINE LEARNING (first 30 minutes)

Minute  Global RPS  hourly_baselines[hour]       Status
──────────────────────────────────────────────────────────
0       45          [45]                         warming up (1/30)
1       48          [45, 48]                     warming up (2/30)
2       47          [45, 48, 47]                 warming up (3/30)
...
29      52          [45, 48, 47, ..., 52]        ready! (30/30)
30      49          [48, 47, ..., 52, 49]        ← 45 evicted (maxlen=1800)
        (maxlen kicks in, oldest dropped)

At 30-minute mark:
  mean = (45+48+47+...+52) / 30 = 48.2
  std = sqrt(variance) = 3.5
  ► state.current_mean[14] = 48.2
  ► state.current_std[14] = 3.5
```

### Per-Hour Switching

```
Hour 13 (0:00 - 0:59)
├─ Accumulates samples
├─ 30 samples ✓ → mean=50.0, std=4.1
└─ stored in current_mean[13], current_std[13]

Hour 14 starts (1:00)
├─ hourly_baselines[14].clear() → fresh deque
├─ New samples start accumulating
├─ Detector uses current_mean[14] (initially 1.0 placeholder)
├─ After 30 min → mean=45.0, std=3.2
└─ stored in current_mean[14], current_std[14]

Why this works:
- Diurnal patterns: Peak traffic hours (9am-5pm) vs low (2am-4am)
- Captures weekly patterns: Mon-Fri vs weekend
- Per-hour stats adapt without throwing away historical data
```

---

## Anomaly Detection Algorithm

### Pseudocode

```python
def detect_anomaly(log, state):
    """
    Two-condition detection with adaptive thresholds.
    """
    ip = log["source_ip"]
    status = log["status"]
    now = time.time()
    
    # Update windows
    state.ip_windows[ip].append(now)
    state.global_window.append(now)
    
    # Evict old entries
    evict(state.ip_windows[ip], now, WINDOW)
    evict(state.global_window, now, WINDOW)
    
    # Calculate rates
    rate_ip = len(state.ip_windows[ip])
    rate_global = len(state.global_window)
    
    # Get baseline
    hour = time.localtime().tm_hour
    mean = state.current_mean[hour]
    std = max(state.current_std[hour], 0.1)
    
    # Condition 1: Z-Score
    z_score = (rate_ip - mean) / std
    
    # Adaptive threshold based on error rate
    threshold = 3.0
    if error_rate(ip, state) > 0.03:  # 3x baseline 1%
        threshold = 2.0
    
    # Detect
    anomalous = (z_score > threshold) or (rate_ip > 5 * mean)
    
    if anomalous and ip not in state.banned_ips:
        # Block the IP
        block_ip(ip)
        state.offenses[ip] += 1
        
        # Determine duration
        duration = BAN_DURATIONS[state.offenses[ip] - 1] or None
        
        # Track
        state.banned_ips[ip] = {
            "expires": now + duration if duration else float('inf'),
            "offense_count": state.offenses[ip],
            "reason": "z_score" if z_score > threshold else "spike"
        }
        
        # Notify
        send_slack_alert(...)
        
        # Audit log
        write_audit_log(...)
```

### Detection Sensitivity Matrix

```
                    Normal Traffic    Spike    DDoS
─────────────────────────────────────────────────────
Rate (req/s)           40             200      1000
Baseline Mean          40              40        40
Z-Score               0.0            +40       +240
5x Baseline Check     No              Yes       Yes
Result               ALLOW           BLOCK     BLOCK
```

---

## Blocking & Unblocking

### IP Blocking Flow

```
┌──────────────────────────────┐
│ Anomaly Detected             │
│ (z_score > 3.0 or spike)     │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ block_ip(ip, duration)       │
│ └─► subprocess.run(          │
│     iptables -A INPUT        │
│     -s <IP> -j DROP          │
│ )                            │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ state.offenses[ip] += 1      │
│ state.banned_ips[ip] = {...} │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ send_slack_alert()           │
│ write_audit_log()            │
│ state.save_state()           │
└──────────────────────────────┘
```

### IP Unblocking Flow (Backoff)

```
Every 10 seconds, unban_worker() checks:

┌──────────────────────────────┐
│ Check banned_ips expiry      │
│ now >= expires?              │
└───────────────┬──────────────┘
                │ YES
┌───────────────▼──────────────┐
│ unblock_ip(ip)               │
│ └─► subprocess.run(          │
│     iptables -D INPUT        │
│     -s <IP> -j DROP          │
│ )                            │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ del banned_ips[ip]           │
│ send_slack_alert("UNBAN")    │
│ write_audit_log("UNBAN")     │
│ state.save_state()           │
└──────────────────────────────┘
```

### Escalation Example

```
IP: 203.0.113.99

1st anomaly detected (14:00):
  ├─ Blocked for 600s (10 min)
  ├─ Ban expires at 14:10
  └─ offense_count = 1

2nd anomaly detected (14:05):
  ├─ Already banned, ignored
  └─ offense_count still 1

1st ban expires (14:10):
  ├─ unblock_ip(203.0.113.99)
  ├─ Slack: "✅ IP UNBANNED"
  └─ banned_ips cleared

3rd anomaly detected (14:12):
  ├─ Blocked for 1800s (30 min)
  ├─ Ban expires at 14:42
  └─ offense_count = 2 (escalated!)

And so on... 3rd: 2h, 4th+: permanent
```

---

## Audit Trail Format

### Log Entry Structure

```
[TIMESTAMP] ACTION | field1=value1 | field2=value2 | ...
```

### Examples

**Ban Entry:**
```
[2024-05-11 14:23:45] BAN | ip=203.0.113.99 | condition=z_score | rate=120 | baseline=40.00 | duration=600
```

**Unban Entry:**
```
[2024-05-11 14:33:45] UNBAN | ip=203.0.113.99 | offense_count=1 | duration=600
```

**Baseline Entry:**
```
[2024-05-11 14:23:00] BASELINE | hour=14 | mean=45.32 | std=4.21
```

### Parsing Example (regex)

```
BAN entry:  \[(.+?)\] BAN \| ip=(.+?) \| condition=(.+?) \| rate=(\d+) \| baseline=([\d.]+) \| duration=(\d+)
UNBAN entry: \[(.+?)\] UNBAN \| ip=(.+?) \| offense_count=(\d+) \| duration=(.+)
```

---

## Performance Considerations

### Memory Usage

```
Typical memory footprint (1000 unique IPs):

ip_windows[ip]:               1000 IPs × 60 entries × 8 bytes = 480 KB
global_window:                60 entries × 8 bytes = 480 bytes
ip_requests/ip_errors:        1000 × 2 × 28 bytes = 56 KB
banned_ips:                   100 bans × 150 bytes = 15 KB
hourly_baselines:             24 hours × 1800 samples × 24 bytes = 1 MB

Total: ~2 MB (scales roughly with number of unique IPs)
```

### CPU Usage

```
Detector thread:             ~0.1% (I/O bound, processes logs as they arrive)
Baseline thread:             ~0.01% (runs 60s interval)
Unban thread:                ~0.01% (runs 10s interval)
Dashboard thread:            ~0.1% (I/O bound, serves on-demand)
Total:                       ~0.2% CPU

Expected: < 1% CPU on 2-vCPU system
```

### Latency

```
Ban detection latency:
  Log written by Nginx ──► Tailer reads ──► Queue ──► Detector ──► iptables
  < 100 ms (typically < 50 ms)

Baseline recalculation:
  Per-second sample ──► 60s interval check ──► statistics.mean() ──► Update
  ~50-200 ms (non-blocking)

Unban check:
  10s poll interval ──► Check expiry ──► iptables remove
  Up to 10s delay (acceptable for auto-unban)
```

---

## Failure Modes & Recovery

### Failure: Log file rotation

**Problem:** Nginx rotates log file daily, tailer might miss new logs
**Solution:** tail_logs() checks file stat, seeks to new file on rotation
**Recovery:** Automatic (monitor.py handles)

### Failure: iptables not available

**Problem:** iptables command fails (running without privilege)
**Solution:** Docker runs with `privileged: true` and `network_mode: host`
**Recovery:** Manual: Run `docker exec anomaly-detector sudo iptables ...`

### Failure: Slack webhook invalid

**Problem:** Alert fails to post
**Solution:** Errors logged but don't stop detection
**Recovery:** Update webhook URL in config.yaml, no restart needed (reloaded per-alert)

### Failure: Baseline not ready

**Problem:** < 30 minutes of data, baseline not initialized
**Solution:** current_mean and current_std have floor defaults (1.0, 0.1)
**Recovery:** Automatic - thresholds loosen until baseline ready

### Failure: Daemon crashes

**Problem:** Process exits unexpectedly
**Solution:** Docker `restart: always` automatically restarts
**Recovery:** Bans persisted in state_store.json, iptables rules remain active

---

## Security Considerations

### Thread Safety

- All state modifications protected by `state.lock` (RLock)
- No race conditions on deque operations (atomic in CPython due to GIL)
- JSON save is atomic (write to tmp, then rename)

### Privilege Escalation

- Daemon runs as `root` in Docker container
- iptables rules are local to container network namespace
- Real host iptables protected by Linux kernel access controls

### Input Validation

- All JSON from Nginx assumed valid (trusted source)
- Source IPs validated as dotted-quad format
- iptables arguments passed via subprocess list (no shell injection)

### DoS Protection

- Unbounded ip_windows deque? No, eviction keeps max size ~100 per IP
- Queue unbounded? Yes, but log generation rate-limited by Nginx
- Memory leak via new IPs? No, old deques automatically cleaned by eviction

---

## Testing Checklist

- [ ] Log tailer successfully reads Nginx JSON logs
- [ ] Baseline reaches 30 samples after 30 minutes
- [ ] Z-score detection triggers on synthetic spike
- [ ] iptables rules appear in `iptables -L -n`
- [ ] Slack alerts deliver correctly
- [ ] Unban worker releases IPs after timeout
- [ ] State persists across daemon restart
- [ ] Dashboard accessible on port 8000
- [ ] Audit log records all actions with timestamps

---

## Future Enhancements

1. **Machine Learning** - Replace z-score with LSTM for multivariate anomaly detection
2. **Geo-Blocking** - GeoIP database integration to block entire countries
3. **Rate Limiting** - In-process rate limiter instead of binary block
4. **Clustering** - Distributed ban list across multiple detector instances
5. **eBPF** - Replace iptables with eBPF for kernel-level traffic shaping
6. **Web UI Authentication** - Protect dashboard with OAuth2
7. **Custom Rules** - DSL for user-defined detection rules
8. **Alert Channels** - Support Opsgenie, PagerDuty, email, SMS

---

**Document Version:** 1.0  
**Last Updated:** May 11, 2024  
**Status:** Complete
