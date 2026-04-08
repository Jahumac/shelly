# Deploying Shelly

Shelly runs as a Docker container. Your data stays on your machine — nothing is sent to the cloud.

---

## Option A — Docker (any machine)

### Step 1 — Pull the image

```bash
docker pull ghcr.io/jahumac/shelly-finance:latest
```

### Step 2 — Run the container

```bash
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /path/to/shelly-data:/app/data \
  ghcr.io/jahumac/shelly-finance:latest
```

Replace `/path/to/shelly-data` with wherever you want Shelly to store its database. For example:
- **Mac/Linux:** `~/shelly-data`
- **Unraid:** `/mnt/user/appdata/shelly/data`

What each flag does:
- `-d` — runs in the background
- `--restart unless-stopped` — auto-starts on reboot
- `-p 8000:8000` — makes it accessible on port 8000 (change the left number if that port is taken, e.g. `-p 8001:8000`)
- `-v .../data:/app/data` — persists your database and secret key outside the container

### Step 3 — Open it

Go to **http://localhost:8000** (or replace `localhost` with your server's IP).

You'll see the setup screen the first time — create your account and you're in.

---

## Option B — Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  shelly:
    image: ghcr.io/jahumac/shelly-finance:latest
    container_name: shelly
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

Then run:

```bash
docker compose up -d
```

---

## Option C — Unraid

### From Community Apps (recommended)

Search for **Shelly** in the Unraid Community Apps store and click Install. Set the data path to `/mnt/user/appdata/shelly/data` and pick your port.

### Manual install via SSH

```bash
ssh root@YOUR_UNRAID_IP
docker pull ghcr.io/jahumac/shelly-finance:latest
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /mnt/user/appdata/shelly/data:/app/data \
  ghcr.io/jahumac/shelly-finance:latest
```

Then open **http://YOUR_UNRAID_IP:8000** in your browser.

---

## Updating

Pull the latest image and recreate the container:

```bash
docker pull ghcr.io/jahumac/shelly-finance:latest
docker stop shelly
docker rm shelly
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /path/to/shelly-data:/app/data \
  ghcr.io/jahumac/shelly-finance:latest
```

Or with Docker Compose:

```bash
docker compose pull
docker compose up -d
```

Your data is safe — it lives in the volume you mounted and is not touched by updates.

---

## Checking logs

```bash
docker logs shelly
# or follow live:
docker logs -f shelly
```

---

## Building from source

If you prefer to build the image yourself rather than using the pre-built one:

```bash
git clone https://github.com/Jahumac/shelly-finance.git
cd shelly-finance
docker build -t shelly .
docker run -d \
  --name shelly \
  --restart unless-stopped \
  -p 8000:8000 \
  -v ./data:/app/data \
  shelly
```
