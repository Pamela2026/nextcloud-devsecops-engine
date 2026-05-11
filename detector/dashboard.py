from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import psutil
import time
import state

app = FastAPI()


@app.get("/metrics")
def metrics():

    top_ips = sorted(
        [(ip, len(q)) for ip, q in state.ip_windows.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return {
        "global_rps": len(state.global_window),
        "banned_ips": list(state.banned_ips.keys()),
        "top_ips": top_ips,
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "mean": getattr(state, "current_mean", 0.0),
        "stddev": getattr(state, "current_std", 0.0),
        "uptime": int(time.time() - getattr(state, "start_time", time.time()))
    }


@app.get("/", response_class=HTMLResponse)
    return """
<!DOCTYPE html>
<html>
<head>
    <title>DevSecOps SOC Dashboard</title>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        body {
            background: #0b0f19;
            color: #e5e7eb;
            font-family: Arial, sans-serif;
            margin: 0;
        }

        .header {
            padding: 20px;
            font-size: 22px;
            font-weight: bold;
            background: #111827;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            padding: 20px;
        }

        .card {
            background: #111827;
            padding: 15px;
            border-radius: 10px;
            border: 1px solid #1f2937;
        }

        .danger {
            color: #ef4444;
            font-weight: bold;
        }

        .ok {
            color: #22c55e;
        }

        #chart-container {
            padding: 20px;
        }

        #alerts {
            padding: 20px;
        }

        .alert {
            background: #7f1d1d;
            padding: 10px;
            margin: 5px 0;
            border-radius: 6px;
        }
    </style>
</head>

<body>

<div class="header">
    🛡 DevSecOps Anomaly Detection Dashboard
</div>

<div class="grid">
    <div class="card">
        <div>Global RPS</div>
        <h2 id="rps">0</h2>
    </div>

    <div class="card">
        <div>CPU</div>
        <h2 id="cpu">0%</h2>
    </div>

    <div class="card">
        <div>Memory</div>
        <h2 id="memory">0%</h2>
    </div>

    <div class="card">
        <div>Banned IPs</div>
        <h2 id="banned">0</h2>
    </div>
</div>

<div id="chart-container">
    <canvas id="chart"></canvas>
</div>

<div id="alerts">
    <h3>🚨 Threat Feed</h3>
    <div id="feed"></div>
</div>


<script>

let labels = [];
let values = [];

const ctx = document.getElementById('chart');

const chart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: labels,
        datasets: [{
            label: 'RPS Spike Detection',
            data: values,
            borderColor: '#3b82f6',
            tension: 0.3
        }]
    }
});


async function refresh() {

    const res = await fetch('/metrics');
    const data = await res.json();

    document.getElementById('rps').innerText = data.global_rps;
    document.getElementById('cpu').innerText = data.cpu + "%";
    document.getElementById('memory').innerText = data.memory + "%";
    document.getElementById('banned').innerText = data.banned_ips.length;

    // spike detection alert
    if (data.global_rps > 50) {
        const alertBox = document.getElementById('feed');
        const div = document.createElement('div');
        div.className = "alert";
        div.innerText = "⚠ HIGH TRAFFIC DETECTED - possible attack spike";
        alertBox.prepend(div);
    }

    labels.push(new Date().toLocaleTimeString());
    values.push(data.global_rps);

    if (labels.length > 30) {
        labels.shift();
        values.shift();
    }

    chart.update();
}

setInterval(refresh, 2000);

</script>

</body>
</html>
"""
