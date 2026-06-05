# VPS Deployment Guide

This guide covers deploying the VoltWatch backend and dashboard to a Linux Virtual Private Server (VPS), such as a DigitalOcean Droplet or AWS EC2 instance.

## 1. System Preparation
Update the server and install necessary tools:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git nginx -y
```

## 2. Clone and Setup
```bash
git clone https://github.com/yourusername/VoltWatch.git
cd VoltWatch
```

## 3. Systemd Services
To keep the apps running after you log out, create systemd service files.

### Backend Service (`/etc/systemd/system/voltwatch-backend.service`)
```ini
[Unit]
Description=VoltWatch FastAPI Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/VoltWatch/backend
ExecStart=/home/ubuntu/VoltWatch/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
EnvironmentFile=/home/ubuntu/VoltWatch/backend/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

### Dashboard Service (`/etc/systemd/system/voltwatch-dashboard.service`)
```ini
[Unit]
Description=VoltWatch Streamlit Dashboard
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/VoltWatch/dashboard
ExecStart=/home/ubuntu/VoltWatch/dashboard/.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1
EnvironmentFile=/home/ubuntu/VoltWatch/dashboard/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable voltwatch-backend voltwatch-dashboard
sudo systemctl start voltwatch-backend voltwatch-dashboard
```

## 4. Nginx Reverse Proxy
To expose your dashboard securely over the web, configure Nginx to proxy port 80/443 to the Streamlit app.

```nginx
server {
    listen 80;
    server_name dashboard.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Restart Nginx: `sudo systemctl restart nginx`. 
*Note: Use Certbot to acquire a free SSL certificate for HTTPS.*
