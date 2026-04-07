# Deploying Shelly to Unraid

This guide deploys Shelly as a Docker container on Unraid, accessible on your local network.

---

## What you need

- Unraid server running
- SSH access to Unraid (Settings → Management Access → SSH)
- The `finance-dashboard-v2` folder on your Mac (already have it)

---

## Step 1 — Copy the app to your Unraid server

From your **Mac terminal** (not Unraid), run:

```bash
scp -r /path/to/finance-dashboard-v2 root@10.1.1.4:/mnt/user/appdata/shelly
```

Replace:
- `/path/to/finance-dashboard-v2` with the actual path to your project folder on your Mac
- `10.1.1.4` with your Unraid server's IP (e.g. `192.168.1.100`)

> **Tip:** To find your Unraid IP — open the Unraid web UI, it's shown in the top-left corner.

---

## Step 2 — SSH into Unraid

```bash
ssh root@10.1.1.4
```

---

## Step 3 — Build the Docker image

```bash
cd /mnt/user/appdata/shelly
docker build -t shelly-app .
```

This will take a minute or two the first time as it downloads Python and installs packages.

---

## Step 4 — Run the container

```bash
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8001:8000 \
  -v /mnt/user/appdata/shelly/data:/app/data \
  shelly-app
```

What each flag does:
- `-d` — runs in the background
- `--restart unless-stopped` — auto-starts on Unraid reboot
- `-p 8001:8000` — makes it accessible on port 8001 (maps to port 8000 inside the container)
- `-v .../data:/app/data` — persists your database and secret key outside the container

---

## Step 5 — Open it in your browser

Go to: **http://10.1.1.4:8001**

You'll see the setup screen the first time — create your admin account and you're in.

---

## How to update the app in future

When you've made changes on your Mac and want to push them to the server:

```bash
# 1. Copy updated files to Unraid
scp -r /path/to/finance-dashboard-v2 root@10.1.1.4:/mnt/user/appdata/shelly

# 2. SSH in
ssh root@10.1.1.4

# 3. Rebuild and restart
cd /mnt/user/appdata/shelly
docker build -t shelly-app .
docker stop shelly
docker rm shelly
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8001:8000 \
  -v /mnt/user/appdata/shelly/data:/app/data \
  shelly-app
```

Your data is safe — it lives in `/mnt/user/appdata/shelly/data/` on the Unraid disk and is not touched by rebuilds.

---

## Checking logs if something goes wrong

```bash
docker logs shelly
# or follow live:
docker logs -f shelly
```

---

## Using a different port

If port 8001 is also taken, change `-p 8001:8000` to any free port, e.g. `-p 8080:8000`, and access it at `http://10.1.1.4:8080`. The left number is the host port (what you type in the browser); the right number (8000) is internal to the container and never changes.

---

## Visible to Unraid Docker UI?

Yes — after `docker run`, open the Unraid web UI → Docker tab and Shelly will appear there. You can start/stop/restart it from the UI and see its port mapping.
