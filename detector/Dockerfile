FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    iptables \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements_new.txt

# Create audit log file
RUN touch audit.log

# Run with unbuffered output for real-time logs
ENTRYPOINT ["python", "-u", "main.py"]
