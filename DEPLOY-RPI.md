# Deploying Resumify on a Raspberry Pi (local network)

This runs the Flask app under gunicorn on your Pi, auto-starting on boot and
reachable from any device on your home network at `http://<pi-ip>:5000`.

It's a plain Python web app — no browser engine, no Docker, no GPU. Everything
in `requirements.txt` installs from prebuilt aarch64 wheels, so a Pi 3 or newer
running 64-bit Raspberry Pi OS handles it comfortably.

## 1. Get the code onto the Pi

SSH into the Pi (or use a keyboard/monitor), then:

```bash
git clone https://github.com/Abhishek-e/Resume-ATS-Tailor.git ~/Resume-ATS-Tailor
cd ~/Resume-ATS-Tailor
```

## 2. Copy the two secret files (they are NOT in git)

`.env` and `serviceAccountKey.json` are gitignored, so the clone doesn't
include them. From **your Mac**, in the project folder, copy them over
(replace `<pi-ip>` with the Pi's address, e.g. `192.168.1.42`):

```bash
scp .env serviceAccountKey.json pi@<pi-ip>:~/Resume-ATS-Tailor/
```

If you'd rather create `.env` fresh on the Pi, use the template:

```bash
cp .env.example .env && nano .env
```

Make sure `.env` has `FLASK_DEBUG=false` and a strong `SECRET_KEY`
(`python3 -c "import secrets; print(secrets.token_hex(32))"`).

## 3. Install dependencies

```bash
bash deploy/setup-pi.sh
```

This installs the needed apt packages, creates a `.venv`, installs the Python
deps, and warns if either secret file is missing.

## 4. Quick test (foreground)

```bash
source .venv/bin/activate
gunicorn app:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:5000
```

From another device on the network, open `http://<pi-ip>:5000`. Ctrl-C to stop.

> Keep `--workers 1`: the live job-listing cache lives in process memory, so a
> second worker would hold its own copy and "Refresh listings" would only
> update one of them. Threads give concurrency without that split.

## 5. Run on boot (systemd)

```bash
sudo cp deploy/resume-ats.service /etc/systemd/system/resume-ats.service
# If your Linux username or path isn't 'pi' / /home/pi, edit those lines first:
#   sudo nano /etc/systemd/system/resume-ats.service
sudo systemctl daemon-reload
sudo systemctl enable --now resume-ats
systemctl status resume-ats          # should say active (running)
journalctl -u resume-ats -f          # live logs
```

The app now starts automatically after every reboot and restarts on crash.
After pulling new code (`git pull`), apply it with:

```bash
sudo systemctl restart resume-ats
```

## 6. Reach it by name (optional)

Raspberry Pi OS advertises itself over mDNS, so instead of the IP you can
usually use `http://<hostname>.local:5000` (e.g. `http://raspberrypi.local:5000`).

To give the Pi a fixed IP, set a DHCP reservation in your router for the Pi's
MAC address — steadier than the IP changing on you.

## Notes & gotchas

- **Google sign-in (Firebase):** the Google button only works from domains
  listed under Firebase Console → Authentication → Settings → Authorized
  domains. A raw `192.168.x.x` / `.local` address won't be authorized, so
  Google sign-in fails on a LAN deployment. Email/password sign-in and
  everything else work fine. Leave `FIREBASE_WEB_API_KEY` blank to hide the
  button entirely.
- **HTTP only:** this is plain HTTP on your LAN. Fine for home use; don't
  expose it to the public internet without a reverse proxy + TLS
  (e.g. Caddy or nginx) and a real domain.
- **First install is slow:** `firebase-admin`/`grpcio` are large wheels — the
  first `pip install` can take a few minutes on a Pi. That's normal.
- **32-bit OS:** prefer 64-bit Raspberry Pi OS. Some wheels (grpcio) build from
  source on 32-bit and are much slower; `setup-pi.sh` installs the build tools
  so it still works, just be patient.
