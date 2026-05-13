# HNG DevSecOps Engine - Quick Reference

## 🚀 Quick Start (5 minutes)

```bash
# 1. Clone and enter directory
git clone <repo-url>
cd nextcloud-devsecops-engine

# 2. Configure Slack webhook (optional but recommended)
nano detector/config.yaml
# Update: slack_webhook: "https://hooks.slack.com/..."

# 3. Deploy
docker compose up -d

# 4. Verify running
docker compose ps

# 5. Access dashboard
# Browser: http://<your-vps-ip>:8000
```

---

## 📊 Key Commands

```bash
# View all daemon logs
docker logs -f anomaly-detector

# View recent detections
docker logs anomaly-detector | grep "ANOMALY DETECTED"

# View audit trail
docker exec anomaly-detector tail -f audit.log

# Check banned IPs (iptables)
docker exec anomaly-detector sudo iptables -L -n | grep DROP

# View metrics JSON
curl http://localhost:8000/metrics | jq

# View current state
docker exec anomaly-detector cat state_store.json | jq

# Stop the daemon
docker compose down

# Restart daemon (keeps state)
docker compose restart anomaly-detector

# View config
docker exec anomaly-detector cat config.yaml
```

---

## 🔍 What Gets Monitored

- **Source IP** - All external IPs (internal 10.*, 172.*, 192.168.* skipped)
- **Request Rate** - Requests per second per IP (60-second window)
- **Error Rate** - 4xx/5xx responses ratio
- **Global Trend** - Total platform RPS

---

## 🚫 How IPs Get Blocked

```
Anomaly Condition Met?
│
├─ z_score > 3.0  OR
├─ rate > 5x baseline  OR
└─ error_rate > 3x baseline
    │
    ▼
Already banned?
│
├─ YES → Skip (already blocked)
│
└─ NO
    │
    ▼ Add iptables DROP rule
    ▼ Send Slack alert
    ▼ Log to audit trail
    ▼ Schedule auto-unban based on offense count
```

---

## ⏱️ Ban Duration Schedule

| Offense # | Duration | Timing |
|-----------|----------|--------|
| 1st | 10 min | After 1st anomaly |
| 2nd | 30 min | If re-triggered after unbanning |
| 3rd | 2 hours | If re-triggered again |
| 4th+ | ∞ Permanent | Chronic attacker |

---

## 📈 Understanding the Metrics

### Dashboard Meaning

| Metric | What It Means | Good Range |
|--------|---------------|-----------|
| **Global RPS** | Total requests/sec | < 50 |
| **Banned IPs** | Currently blocked | 0-2 |
| **CPU** | Processor usage | < 5% |
| **Memory** | RAM usage | 5-15% |
| **Baseline Mean** | Normal traffic level | Per hour |
| **Baseline Stddev** | Traffic variance | Small |

### Detection Examples

```
Normal Day:
  Baseline: mean=40 req/s, std=5
  Current: 45 req/s
  z_score = (45-40)/5 = 1.0 ✅ ALLOWED

Sudden Spike:
  Baseline: mean=40 req/s, std=5
  Current: 250 req/s
  z_score = (250-40)/5 = 42.0 ❌ BLOCKED
  Also: 250 > (5*40) = 200 ❌ BLOCKED (5x trigger)

High Error Rate:
  100 requests, 5 errors (5% error rate)
  Baseline error: 1%
  5% > (3*1%) = 3% ❌ THRESHOLD LOWERED
  (z_score threshold drops from 3.0 to 2.0)
```

---

## 🔧 Configuration Parameters

Edit `detector/config.yaml`:

```yaml
# Slack webhook (leave empty to disable alerts)
slack_webhook: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Detection thresholds
thresholds:
  z_score: 3.0              # Higher = less sensitive
  spike_multiplier: 5       # Higher = less sensitive

# Ban escalation (in seconds)
ban_durations:
  - 600                     # 10 minutes (1st offense)
  - 1800                    # 30 minutes (2nd)
  - 7200                    # 2 hours (3rd)

# Dashboard web server
dashboard_port: 8000        # Access at http://<ip>:8000
```

---

## 🐛 Troubleshooting Flowchart

```
Problem: Daemon not starting
├─ Check logs: docker logs anomaly-detector
├─ Config syntax error? → Fix YAML, redeploy
├─ Dependencies missing? → docker compose build --no-cache
└─ Restart: docker compose down && docker compose up -d

Problem: No logs being processed
├─ Check Nginx logs: docker exec hng-nginx ls -la /var/log/nginx/
├─ Check volume: docker exec anomaly-detector ls -la /logs/
├─ Generate traffic: curl http://localhost/ × 10
└─ Check detector sees it: docker logs anomaly-detector | tail

Problem: IPs not being blocked
├─ Check baseline ready: docker logs anomaly-detector | grep "BASELINE"
├─ Generate attack traffic
├─ Check detection: docker logs anomaly-detector | grep "ANOMALY"
├─ Check iptables: docker exec anomaly-detector sudo iptables -L -n
└─ Manually test: docker exec anomaly-detector sudo iptables -A INPUT -s <test-ip> -j DROP

Problem: Slack alerts not sending
├─ Verify webhook: cat detector/config.yaml | grep slack_webhook
├─ Test manually: curl -X POST <webhook> -d '{"text":"Test"}'
├─ Check network: docker exec anomaly-detector curl slack.com
└─ Check logs: docker logs anomaly-detector | grep -i slack

Problem: Dashboard not accessible
├─ Check port: docker exec anomaly-detector netstat -tlnp | grep 8000
├─ Check firewall: sudo ufw allow 8000/tcp
├─ Test locally: docker exec anomaly-detector curl http://localhost:8000
└─ Test from host: curl http://localhost:8000
```

---

## 📋 Files Overview

```
detector/
  ├─ main.py              ← Entry point, starts all threads
  ├─ monitor.py           ← Reads Nginx logs
  ├─ baseline.py          ← Calculates rolling baseline
  ├─ detector.py          ← Anomaly detection logic ⭐
  ├─ blocker.py           ← iptables integration
  ├─ unbanner.py          ← Auto-unban scheduler
  ├─ notifier.py          ← Slack alerts
  ├─ dashboard.py         ← Web UI (FastAPI)
  ├─ state.py             ← Shared state + persistence
  ├─ spike_sim.py         ← Test traffic generator
  ├─ config.yaml          ← Configuration ⭐
  ├─ Dockerfile           ← Container image
  ├─ requirements_new.txt  ← Python dependencies
  ├─ audit.log            ← Audit trail
  └─ state_store.json     ← Persistent state

nginx/
  └─ nginx.conf           ← Reverse proxy config ⭐

docs/
  └─ ARCHITECTURE.md      ← Detailed design ⭐

├─ docker-compose.yaml    ← Service orchestration ⭐
├─ README.md              ← Setup & overview ⭐
└─ IMPLEMENTATION_GUIDE.md ← This project guide ⭐

⭐ = Most important files to understand first
```

---

## 🎯 Performance Targets

```
Detection Latency:   < 100ms (from log write to iptables)
Baseline Update:     60 seconds
Unban Check:         10 seconds
Dashboard Refresh:   3 seconds

Memory Usage:        ~2-5 MB
CPU Usage:           0.2-0.5% (on 2-vCPU system)
Max Throughput:      10k+ req/s supported
```

---

## 📱 Slack Alert Types

### Ban Alert
```
🚨 HNG ANOMALY DETECTED
IP: 203.0.113.99
Condition: z_score / spike_multiplier
Rate: 250 req/s
Baseline: 40 req/s
Z-Score: 42.0
Ban Duration: 600s
```

### Unban Alert
```
✅ IP UNBANNED
IP: 203.0.113.99
Offense Count: 1
Ban Duration: 600s
```

---

## 🔒 Security Notes

- Daemon runs as root in container (necessary for iptables)
- Host network mode used (privileged: true in docker-compose)
- Dashboard should be restricted to admin IPs (firewall)
- State file contains sensitive IP data (backup safely)
- Slack webhook is sensitive (keep in env, not git)

---

## 🧪 Testing Workflow

```
1. Deploy: docker compose up -d
2. Wait for baseline: 30+ minutes OR use spike generator
3. Generate traffic: for i in {1..1000}; do curl http://localhost/ & done
4. Monitor detection: docker logs -f anomaly-detector
5. Check blocked IPs: docker exec anomaly-detector sudo iptables -L -n
6. Verify Slack alerts: Check channel
7. Wait for auto-unban: 10+ minutes for 1st ban to expire
8. Verify unblock: Check iptables rules cleared
```

---

## 💡 Pro Tips

- Keep terminal window open with: `docker logs -f anomaly-detector`
- Check dashboard in another window: `http://<ip>:8000`
- Tail audit log for analysis: `docker exec anomaly-detector tail -f audit.log`
- Export metrics for analysis: `curl http://localhost:8000/metrics | jq > metrics.json`
- Backup state before deployments: `docker cp anomaly-detector:/app/state_store.json ./backup/`

---

## 📚 Learn More

| Topic | File |
|-------|------|
| Full architecture | docs/ARCHITECTURE.md |
| Setup instructions | README.md |
| Implementation details | IMPLEMENTATION_GUIDE.md |
| Code walkthrough | detector/*.py (read in order of main.py references) |

---

## ✅ Pre-Submission Checklist

- [ ] Daemon running 12+ continuous hours
- [ ] Baseline learned (≥30 min of data)
- [ ] Dashboard accessible at `http://<ip>:8000`
- [ ] Slack webhook configured and alerts working
- [ ] Screenshots captured:
  - [ ] Tool running (`docker logs` output)
  - [ ] Ban alert (Slack)
  - [ ] Unban alert (Slack)
  - [ ] Global alert (Slack)
  - [ ] iptables rules (`sudo iptables -L -n`)
  - [ ] Audit log entries
  - [ ] Baseline graph over 2+ hours
- [ ] README with server IP & dashboard URL
- [ ] Blog post published on Hashnode/Dev.to
- [ ] GitHub repo is public

---

## 🎯 Success Criteria

✅ Real-time threat detection working
✅ Automatic IP blocking via iptables
✅ Ban/unban lifecycle functioning
✅ Slack notifications reliable
✅ Dashboard showing live metrics
✅ Audit trail comprehensive
✅ Code well-documented
✅ Production-ready deployment

---

**Version:** 1.0  
**Last Updated:** May 11, 2024  
**Status:** Ready for Production Deployment
