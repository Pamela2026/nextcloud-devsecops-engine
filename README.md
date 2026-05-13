# HNG DevSecOps - Nextcloud Anomaly Detection Engine

## 🎯 Project Overview

This is a production-ready anomaly detection engine for Nextcloud that runs as a continuous daemon alongside the application. It monitors all incoming HTTP traffic in real-time, learns what "normal" traffic looks like, and automatically blocks malicious IPs that deviate from established baselines.

**Key Features:**
- ✅ Real-time traffic monitoring via Nginx JSON logs
- ✅ Sliding window-based request rate tracking (60-second windows)
- ✅ Rolling 30-minute baseline with per-hour statistics
- ✅ Z-score anomaly detection (threshold: 3.0)
- ✅ Spike detection (5x baseline multiplier)
- ✅ Adaptive thresholds based on error rates
- ✅ Automatic IP blocking via iptables with escalating ban durations
- ✅ Backoff-based auto-unban schedule (10m, 30m, 2h, permanent)
- ✅ Slack alerts for all actions (ban, unban, global anomalies)
- ✅ Live metrics dashboard with real-time refresh (3-second interval)
- ✅ Structured audit logging for compliance and analysis

---

## 🏗️ Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Compose Stack                   │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─────────────────┐    ┌──────────────────┐            │
│  │  Nextcloud App  │◄──┤  Nginx Reverse   │            │
│  │   (Port 80)     │    │  Proxy (Port 80) │            │
│  └─────────────────┘    └──────────────────┘            │
│                              │                           │
│                         ┌────▼──────────────┐           │
│                         │ JSON Access Logs  │           │
│                         │ (named volume)    │           │
│                         └────┬──────────────┘           │
│                              │                           │
│  ┌──────────────────────────▼──────────────────────┐   │
│  │   Anomaly Detection Engine (Python Daemon)      │   │
│  ├───────────────────────────────────────────────┤   │
│  │ • Log Tailer: Continuous log file monitoring  │   │
│  │ • Sliding Window: Deque-based request tracking│   │
│  │ • Baseline Calc: 30-min rolling stats         │   │
│  │ • Detector: Z-score + spike detection         │   │
│  │ • Blocker: iptables DROP rules                │   │
│  │ • Unbanner: Backoff-based auto-unban          │   │
│  │ • Notifier: Slack alerts                      │   │
│  │ • Dashboard: FastAPI + Web UI (Port 8000)     │   │
│  └───────────────────────────────────────────────┘   │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Log Generation**: Nginx writes JSON access logs with source IP, timestamp, method, path, status, response size
2. **Log Monitoring**: Python daemon tails the log file in real-time
3. **Window Tracking**: Timestamps added to per-IP and global deques (60-second FIFO)
4. **Baseline Learning**: Every 60 seconds, current RPS sampled and added to hourly bucket
5. **Anomaly Detection**: Each log checked against baseline; z-score or spike triggers block
6. **Blocking**: iptables DROP rule added for offending IP
7. **Auto-Unban**: Background worker checks expiration times every 10 seconds
8. **Slack Alert**: Immediate notification of block/unban events
9. **Dashboard**: FastAPI server exposes metrics endpoint; HTML UI refreshes every 3 seconds

---

## 📊 Sliding Window Implementation

### Deque-Based Architecture

```python
# Per-IP windows (one deque per IP)
state.ip_windows = defaultdict(deque)  # {ip: deque([ts1, ts2, ts3, ...])}

# Global windows (all requests)
state.global_window = deque()           # deque([ts1, ts2, ts3, ...])

# Window size: 60 seconds (configurable as state.WINDOW)
```

### Eviction Logic

Every time a new request is logged:

1. Append new timestamp to both ip_windows[ip] and global_window
2. Remove all timestamps older than 60 seconds:
   ```python
   while ip_windows[ip] and now - ip_windows[ip][0] > WINDOW:
       ip_windows[ip].popleft()
   ```
3. Calculate current rate = len(window) requests per 60 seconds

**Efficiency:**
- O(1) append, O(n) remove (where n typically << 100)
- No garbage collection overhead
- Timestamp-based eviction ensures accuracy across clock skew

---

## 📈 Baseline System

### Rolling 30-Minute Window

**Data Structure:**
```python
state.hourly_baselines = {
    hour: deque(maxlen=1800)  # 30 min * 60 sec/sample = 1800
    for hour in range(24)
}

state.current_mean = {hour: 1.0 for hour in range(24)}
state.current_std = {hour: 0.1 for hour in range(24)}
```

**Recalculation Every 60 Seconds:**

1. Sample current global RPS (len(global_window))
2. Append to current hour's deque
3. If deque has ≥ 30 samples (30 minutes of data):
   - Calculate mean of all samples
   - Calculate standard deviation
   - Apply floor: mean = max(mean, 1.0), std = max(std, 0.1)
   - Store in state.current_mean[hour] and state.current_std[hour]

**Hour Transition:**
- When clock moves to new hour (localtime().tm_hour changes), baseline switches
- Old hour's stats retained in state.current_mean[old_hour]
- New hour starts accumulating samples from scratch

**Why This Works:**
- 30-minute window smooths out short-term noise
- Per-hour stats capture diurnal traffic patterns (e.g., morning vs. night)
- Floor values prevent division-by-zero and overly-sensitive thresholds

---

## 🔍 Anomaly Detection Logic

### Two-Part Detection

**Condition 1: Z-Score > 3.0**
```
z_score = (current_rate - baseline_mean) / baseline_std

If z_score > 3.0 → ANOMALY
```
- Catches gradual sustained increase

**Condition 2: Rate > 5x Baseline**
```
If current_rate > (5 * baseline_mean) → ANOMALY
```
- Catches sudden spikes even with low absolute rates

### Adaptive Thresholds (Error Surge)

If an IP has error rate (4xx/5xx) > 3x baseline (typically 1%):
- Lower z-score threshold from 3.0 to 2.0
- Indicates potential attack reconnaissance (probing endpoints)
- Tighter detection catches subtle anomalies

### Detection in Action

```
Normal traffic:
  rate=50 req/s, mean=40, std=5
  z_score = (50-40)/5 = 2.0 ✓ ALLOWED

Gradual spike:
  rate=120 req/s, mean=40, std=5
  z_score = (120-40)/5 = 16.0 ✗ BLOCKED (z > 3.0)

Sudden burst:
  rate=220 req/s, mean=40, std=5
  (50*40) = 200 threshold
  220 > 200 ✗ BLOCKED (5x multiplier)

High error rate:
  rate=60 req/s, mean=40, std=5, error_rate=5%
  z_score = 4.0
  threshold lowered to 2.0
  4.0 > 2.0 ✗ BLOCKED (adaptive threshold)
```

---

## 🚫 IP Blocking & Auto-Unban

### Escalating Ban Schedule

| Offense # | Ban Duration | Reason |
|-----------|--------------|--------|
| 1st       | 10 minutes   | Initial anomaly |
| 2nd       | 30 minutes   | Repeated offense |
| 3rd       | 2 hours      | Persistent threat |
| 4th+      | Permanent    | Chronic attacker |

### iptables Integration

When blocking:
```bash
iptables -A INPUT -s <IP> -j DROP
```

When unbanning:
```bash
iptables -D INPUT -s <IP> -j DROP
```

**Note:** Daemon runs with `network_mode: host` and `privileged: true` in Docker to access host iptables.

### State Persistence

Ban data persisted to `state_store.json`:
```json
{
  "offenses": {"203.0.113.99": 2},
  "banned_ips": {
    "203.0.113.99": {
      "expires": 1715420400.5,
      "offense_count": 2,
      "reason": "spike"
    }
  }
}
```

On restart, state is restored so previous offenses aren't forgotten.

---

## 📱 Slack Integration

### Alert Format

**Ban Alert:**
```
🚨 **HNG ANOMALY DETECTED**

**IP:** `203.0.113.99`
**Condition:** z_score
**Rate:** 120 req/s
**Baseline Mean:** 40 req/s
**Stddev:** 5
**Z-Score:** 16.0
**Offense Count:** 1
**Ban Duration:** 600s
**Timestamp:** 2024-05-11 14:23:45
```

**Unban Alert:**
```
✅ **IP UNBANNED**

**IP:** `203.0.113.99`
**Offense Count:** 1
**Ban Duration:** 600s
**Timestamp:** 2024-05-11 14:33:45
```

### Configuration

Set webhook URL in `detector/config.yaml`:
```yaml
slack_webhook: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

---

## 📊 Live Metrics Dashboard

**URL:** `http://<server-ip>:8000`

**Refresh Rate:** Every 3 seconds

**Metrics Displayed:**
- Global Requests/sec (last 60s)
- Banned IPs count
- CPU usage %
- Memory usage %
- Baseline mean (req/s for current hour)
- Baseline stddev
- Engine uptime
- Last update timestamp

**Top 10 IPs Table:**
- Rank, source IP, current req/s, ban status

**Banned IPs Table:**
- IP, reason, offense count, ban expiration

**RPS Trend Chart:**
- Line graph showing global RPS over last 30 data points

---

## 📋 Audit Logging

**Format:**
```
[YYYY-MM-DD HH:MM:SS] ACTION | field1=value1 | field2=value2 | ...
```

**Examples:**

Ban:
```
[2024-05-11 14:23:45] BAN | ip=203.0.113.99 | condition=z_score | rate=120 | baseline=40.00 | duration=600
```

Unban:
```
[2024-05-11 14:33:45] UNBAN | ip=203.0.113.99 | offense_count=1 | duration=600
```

Baseline Recalculation:
```
[2024-05-11 14:23:00] BASELINE | hour=14 | mean=45.32 | std=4.21
```

**File Location:** `detector/audit.log`

**Use Cases:**
- Compliance reporting
- Post-incident analysis
- Pattern detection
- Tuning threshold values

---

## 🚀 Quick Start

### Prerequisites

- Linux VPS with 2+ vCPU, 2 GB RAM
- Docker & Docker Compose installed
- A Slack workspace for alerts (optional)

### Step 1: Clone Repository

```bash
git clone <your-repo-url>
cd nextcloud-devsecops-engine
```

### Step 2: Configure

Edit `detector/config.yaml`:
```yaml
slack_webhook: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

thresholds:
  z_score: 3.0
  spike_multiplier: 5

ban_durations:
  - 600      # 10 min (1st offense)
  - 1800     # 30 min (2nd)
  - 7200     # 2 hrs (3rd)

dashboard_port: 8000
```

### Step 3: Deploy

```bash
docker-compose up -d
```

### Step 4: Verify

```bash
# Check daemon logs
docker logs -f anomaly-detector

# Access dashboard
curl http://localhost:8000

# Check audit log
docker exec anomaly-detector tail -f audit.log

# View banned IPs
docker exec anomaly-detector sudo iptables -L -n | grep DROP
```

---

## 🧪 Testing

### Trigger a Spike (Using Built-in Simulator)

The daemon includes a test spike generator that fires every 8 seconds for testing. Logs should show:
```
[SIM] 🔥 SPIKE ATTACK TRIGGERED
[DETECTOR] ANOMALY DETECTED for 203.0.113.99
[BAN] Blocking IP 203.0.113.99 (duration: 600s)
[SLACK] Alert sent
```

### Manual Testing

Generate traffic from a test IP:
```bash
# From a separate machine
for i in {1..500}; do
  curl http://<server-ip>/ &
done
wait
```

Then check:
```bash
# View dashboard
http://<server-ip>:8000

# Check iptables rules
sudo iptables -L -n | grep DROP

# Check audit log
tail audit.log
```

---

## 📁 Repository Structure

```
nextcloud-devsecops-engine/
├── docker-compose.yaml          # Orchestration config
├── README.md                     # This file
├── detector/
│   ├── main.py                  # Entry point & thread orchestration
│   ├── monitor.py               # Nginx log tailer
│   ├── baseline.py              # Rolling baseline calculation
│   ├── detector.py              # Anomaly detection logic
│   ├── blocker.py               # iptables integration
│   ├── unbanner.py              # Auto-unban worker
│   ├── notifier.py              # Slack alerting
│   ├── dashboard.py             # FastAPI web UI
│   ├── state.py                 # Shared state + persistence
│   ├── spike_sim.py             # Attack simulator for testing
│   ├── config.yaml              # Configuration file
│   ├── requirements_new.txt     # Python dependencies
│   ├── Dockerfile               # Container image
│   ├── audit.log                # Structured audit trail
│   └── state_store.json         # Persistent state (banned IPs, offenses)
├── nginx/
│   └── nginx.conf               # Nginx reverse proxy config
└── docs/
    └── architecture.png          # Architecture diagram
```

---

## ⚙️ Configuration Parameters

### `config.yaml`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slack_webhook` | string | "" | Slack webhook URL for alerts |
| `thresholds.z_score` | float | 3.0 | Z-score anomaly threshold |
| `thresholds.spike_multiplier` | int | 5 | Rate multiplier threshold |
| `ban_durations` | array | [600, 1800, 7200] | Escalating ban durations (seconds) |
| `dashboard_port` | int | 8000 | Port for metrics dashboard |

### Environment Variables

(None required; all config via `config.yaml`)

---

## 🐛 Troubleshooting

### Dashboard not accessible

```bash
# Check if FastAPI is running
docker logs anomaly-detector | grep "Starting dashboard"

# Verify port binding
docker exec anomaly-detector netstat -tlnp | grep 8000

# Check firewall
sudo ufw allow 8000
```

### No logs being processed

```bash
# Verify Nginx is writing logs
docker exec hng-nginx ls -la /var/log/nginx/

# Check log format
docker exec hng-nginx head /var/log/nginx/hng-access.log

# Verify volume mount
docker exec anomaly-detector ls -la /logs/
```

### Iptables rules not applying

```bash
# Check if daemon has privileges
docker exec anomaly-detector sudo iptables -L -n

# Verify daemon is running as host network
docker inspect anomaly-detector | grep NetworkMode

# Manually test iptables
docker exec anomaly-detector sudo iptables -A INPUT -s 203.0.113.99 -j DROP
```

### Slack alerts not sending

```bash
# Verify webhook URL in config.yaml
docker exec anomaly-detector cat config.yaml | grep slack_webhook

# Test webhook manually
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK \
  -H 'Content-Type: application/json' \
  -d '{"text":"Test alert"}'
```

---

## 📈 Performance Tuning

### Baseline Window Size
- Increase from 30 min to 60 min for less noise (edit `state.py`)
- Decrease for faster adaptation to traffic changes

### Z-Score Threshold
- Increase from 3.0 to 4.0 for fewer false positives
- Decrease to 2.5 for more aggressive blocking

### Spike Multiplier
- Increase from 5x to 10x for less sensitivity
- Decrease to 3x for more sensitivity

### Ban Durations
- Reduce for faster recovery (e.g., 300, 900, 3600)
- Increase for stricter penalties (e.g., 1800, 7200, permanent)

---

## 📚 References

- **Z-Score Formula:** (value - mean) / standard_deviation
- **Deque Documentation:** https://docs.python.org/3/collections/#collections.deque
- **iptables Manual:** https://linux.die.net/man/8/iptables
- **Slack API:** https://api.slack.com/messaging/webhooks

---

## 📝 Blog Post

[Link to beginner-friendly blog post explaining the project]
(To be published on Hashnode/Dev.to/Medium)

---

## 👤 Author

**Your Name** - DevSecOps Engineer at HNG Cloud

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- [Nextcloud](https://nextcloud.com/) - File sync platform
- [HNG Internship](https://hng.tech/) - Internship program
- [Kefa Slungu](https://hub.docker.com/u/kefaslungu) - Nextcloud Docker image

---

**Last Updated:** May 11, 2024  
**Status:** Production Ready
