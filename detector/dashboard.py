from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import psutil
import time
import state
import json

app = FastAPI()


@app.get("/metrics")
def metrics():
    """
    Return current metrics as JSON for the dashboard to consume.
    """
    with state.lock:
        top_ips = sorted(
            [(ip, len(q)) for ip, q in state.ip_windows.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        current_hour = time.localtime().tm_hour
        mean = state.current_mean.get(current_hour, 1.0)
        std = state.current_std.get(current_hour, 0.1)
        
        return {
            "global_rps": len(state.global_window),
            "banned_ips": list(state.banned_ips.keys()),
            "banned_count": len(state.banned_ips),
            "top_ips": top_ips,
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
            "mean": mean,
            "stddev": std,
            "uptime": int(time.time() - state.start_time),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }


@app.get("/", response_class=HTMLResponse)
def index():
    """
    Live metrics dashboard with real-time refresh every 2-3 seconds.
    Shows banned IPs, request rates, top source IPs, system metrics.
    """
    return """
<!DOCTYPE html>
<html>
<head>
    <title>HNG DevSecOps - Anomaly Detection Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background: linear-gradient(135deg, #0b0f19 0%, #111827 100%);
            color: #e5e7eb;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            overflow-x: hidden;
        }
        
        .header {
            background: linear-gradient(90deg, #1f2937 0%, #111827 100%);
            padding: 25px;
            border-bottom: 2px solid #3b82f6;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: bold;
        }
        
        .header p {
            font-size: 12px;
            color: #9ca3af;
            margin-top: 5px;
        }
        
        .container {
            max-width: 1400px;
            margin: 20px auto;
            padding: 0 20px;
        }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .metric-card {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        
        .metric-card:hover {
            border-color: #3b82f6;
            box-shadow: 0 0 10px rgba(59, 130, 246, 0.1);
        }
        
        .metric-label {
            font-size: 12px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .metric-value {
            font-size: 32px;
            font-weight: bold;
            margin-top: 10px;
        }
        
        .metric-value.danger {
            color: #ef4444;
        }
        
        .metric-value.warning {
            color: #f59e0b;
        }
        
        .metric-value.ok {
            color: #22c55e;
        }
        
        .metric-sub {
            font-size: 12px;
            color: #6b7280;
            margin-top: 5px;
        }
        
        .section {
            margin-bottom: 30px;
        }
        
        .section-title {
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .chart-container {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 12px;
            padding: 20px;
            position: relative;
            height: 400px;
        }
        
        .table-container {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 12px;
            padding: 20px;
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            text-align: left;
            padding: 12px;
            font-size: 12px;
            text-transform: uppercase;
            color: #9ca3af;
            border-bottom: 1px solid #1f2937;
        }
        
        td {
            padding: 12px;
            border-bottom: 1px solid #1f2937;
        }
        
        tr:hover {
            background: #0f172a;
        }
        
        .ip-banned {
            background: rgba(239, 68, 68, 0.1);
            color: #fca5a5;
            padding: 4px 8px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
        }
        
        .rps-bar {
            background: linear-gradient(90deg, #3b82f6 0%, #0ea5e9 100%);
            height: 20px;
            border-radius: 4px;
            display: inline-block;
            min-width: 2px;
        }
        
        .last-update {
            font-size: 11px;
            color: #6b7280;
            text-align: right;
            margin-top: 10px;
        }
        
        .live-indicator {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
            margin-right: 5px;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
    </style>
</head>
<body>

<div class="header">
    <h1>🛡 HNG DevSecOps Anomaly Detection</h1>
    <p>Real-time threat detection and IP blocking engine</p>
</div>

<div class="container">
    
    <!-- KEY METRICS -->
    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Global Requests/sec</div>
            <div class="metric-value" id="rps">0</div>
            <div class="metric-sub">Last 60s window</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Banned IPs</div>
            <div class="metric-value danger" id="banned">0</div>
            <div class="metric-sub">Currently blocked</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">CPU Usage</div>
            <div class="metric-value" id="cpu">0%</div>
            <div class="metric-sub">System load</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Memory Usage</div>
            <div class="metric-value" id="memory">0%</div>
            <div class="metric-sub">RAM consumption</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Baseline Mean</div>
            <div class="metric-value ok" id="mean">0.0</div>
            <div class="metric-sub">req/s (current hour)</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Baseline Stddev</div>
            <div class="metric-value ok" id="stddev">0.0</div>
            <div class="metric-sub">Standard deviation</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Uptime</div>
            <div class="metric-value ok" id="uptime">0s</div>
            <div class="metric-sub">Engine running</div>
        </div>
        
        <div class="metric-card">
            <div class="metric-label">Last Update</div>
            <div class="metric-value ok" id="timestamp" style="font-size: 14px;">--:--:--</div>
            <div class="metric-sub" id="refresh-status"><span class="live-indicator"></span>Live</div>
        </div>
    </div>
    
    <!-- RPS TREND CHART -->
    <div class="section">
        <div class="section-title">
            📊 Request Rate Trends
        </div>
        <div class="chart-container">
            <canvas id="rpsChart"></canvas>
        </div>
    </div>
    
    <!-- TOP SOURCE IPS -->
    <div class="section">
        <div class="section-title">
            🌐 Top 10 Source IPs (by request volume)
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Source IP</th>
                        <th>Requests/sec</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="top-ips-tbody">
                    <tr><td colspan="4" style="text-align: center; color: #6b7280;">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- BANNED IPS -->
    <div class="section">
        <div class="section-title">
            🚫 Currently Banned IPs
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>IP Address</th>
                        <th>Reason</th>
                        <th>Offense Count</th>
                        <th>Ban Expires</th>
                    </tr>
                </thead>
                <tbody id="banned-ips-tbody">
                    <tr><td colspan="4" style="text-align: center; color: #6b7280;">No IPs currently banned</td></tr>
                </tbody>
            </table>
        </div>
    </div>

</div>

<script>
    // Chart.js setup
    const rpsCtx = document.getElementById('rpsChart').getContext('2d');
    
    const rpsChart = new Chart(rpsCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Global RPS',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                tension: 0.3,
                fill: true,
                pointRadius: 4,
                pointBackgroundColor: '#3b82f6',
                pointBorderColor: '#111827'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#e5e7eb' }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { color: '#9ca3af' },
                    grid: { color: '#1f2937' }
                },
                x: {
                    ticks: { color: '#9ca3af' },
                    grid: { color: '#1f2937' }
                }
            }
        }
    });
    
    // Refresh metrics
    async function refresh() {
        try {
            const res = await fetch('/metrics');
            const data = await res.json();
            
            // Update key metrics
            const rps = data.global_rps;
            document.getElementById('rps').innerText = rps;
            document.getElementById('rps').className = 
                rps > 100 ? 'metric-value danger' : 
                rps > 50 ? 'metric-value warning' : 
                'metric-value ok';
            
            document.getElementById('banned').innerText = data.banned_count;
            document.getElementById('cpu').innerText = Math.round(data.cpu) + '%';
            document.getElementById('memory').innerText = Math.round(data.memory) + '%';
            document.getElementById('mean').innerText = data.mean.toFixed(2);
            document.getElementById('stddev').innerText = data.stddev.toFixed(2);
            document.getElementById('uptime').innerText = formatUptime(data.uptime);
            document.getElementById('timestamp').innerText = data.timestamp;
            
            // Update chart
            rpsChart.data.labels.push(new Date().toLocaleTimeString());
            rpsChart.data.datasets[0].data.push(rps);
            
            if (rpsChart.data.labels.length > 30) {
                rpsChart.data.labels.shift();
                rpsChart.data.datasets[0].data.shift();
            }
            
            rpsChart.update('none');
            
            // Update top IPs table
            const topIpsBody = document.getElementById('top-ips-tbody');
            if (data.top_ips && data.top_ips.length > 0) {
                topIpsBody.innerHTML = data.top_ips.map((item, idx) => {
                    const [ip, rps] = item;
                    const isBanned = data.banned_ips.includes(ip);
                    return `
                        <tr>
                            <td>${idx + 1}</td>
                            <td><span class="${isBanned ? 'ip-banned' : ''}">${ip}</span></td>
                            <td>${rps} req/s</td>
                            <td>${isBanned ? '🚫 BLOCKED' : '✓ Active'}</td>
                        </tr>
                    `;
                }).join('');
            } else {
                topIpsBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #6b7280;">No data yet</td></tr>';
            }
            
            // Update banned IPs table
            const bannedBody = document.getElementById('banned-ips-tbody');
            if (data.banned_ips && data.banned_ips.length > 0) {
                // This is just a list of IPs; we'd need more data to show full details
                bannedBody.innerHTML = data.banned_ips.map(ip => `
                    <tr>
                        <td><span class="ip-banned">${ip}</span></td>
                        <td>Anomaly detection</td>
                        <td>N/A</td>
                        <td>TBD</td>
                    </tr>
                `).join('');
            } else {
                bannedBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #6b7280;">No IPs currently banned</td></tr>';
            }
            
        } catch (error) {
            console.error('Error refreshing metrics:', error);
        }
    }
    
    function formatUptime(seconds) {
        if (seconds < 60) return seconds + 's';
        if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
        if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
        return Math.floor(seconds / 86400) + 'd';
    }
    
    // Refresh every 3 seconds
    setInterval(refresh, 3000);
    refresh(); // Initial load
</script>

</body>
</html>
"""
