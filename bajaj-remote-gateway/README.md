# bajaj-remote-gateway

`bajaj-remote-gateway` is a Python-only reverse proxy bridge for exposing HTTP camera/admin UIs from private networks without VPN, VNC, or GUI remote access.

## Architecture

- **Public Server (FastAPI)**
  - Accepts browser HTTP requests on `/proxy/{target}/{path}`
  - Holds long-lived WebSocket connections from private agents at `/ws/agent`
  - Forwards browser request payloads to the correct agent
  - Returns agent responses back to browser
- **Gateway Agent (Ubuntu Server in private LAN)**
  - Keeps outbound WebSocket connection to public server
  - Receives proxy jobs from server
  - Requests `http://{target}{path}` inside LAN via `httpx`
  - Sends status/body/headers back to server

> Browser never directly reaches private IPs. All access is tunneled through `Server -> Agent -> Camera`.

---

## Project layout

```text
bajaj-remote-gateway/
├── agent/
│   ├── __init__.py
│   ├── main.py
│   ├── ws_client.py
│   ├── proxy_handler.py
│   └── config.py
├── server/
│   ├── __init__.py
│   ├── main.py
│   ├── ws_manager.py
│   ├── proxy_routes.py
│   ├── connection_manager.py
│   └── models.py
├── common/
│   ├── __init__.py
│   └── schemas.py
├── requirements-agent.txt
├── requirements-server.txt
└── README.md
```

---

## Request Flow

1. Agent starts on private Ubuntu host and connects outbound:
   `ws://PUBLIC_SERVER:8000/ws/agent?agent_id=<AGENT_ID>&token=<AGENT_TOKEN>`
2. Browser opens:
   `http://PUBLIC_SERVER:8000/proxy/192.168.1.20:80/`
3. Server sends WebSocket JSON to that agent:
   - method, target, path, headers, body, request id
4. Agent performs LAN request (`http://192.168.1.20:80/`) and returns response JSON.
5. Server rebuilds HTTP response for browser.
6. If HTML, `href="/..."` and `src="/..."` are rewritten to `/proxy/<target>/...`.

---

## Security Controls

- Agent WebSocket authentication via `AGENT_TOKEN`.
- Agent IDs validated (`a-z`, `A-Z`, `0-9`, `_`, `-`).
- Proxy route only works when at least one agent is connected.
- If multiple agents are connected, select one with `?agent_id=<agent_id>`.
- Internal camera targets are never directly internet exposed.

---

## Ubuntu Server Setup (Agent)

```bash
sudo apt update
sudo apt install -y python3 python3-venv

cd /opt
git clone <your-repo-url> bajaj-remote-gateway
cd bajaj-remote-gateway/bajaj-remote-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-agent.txt
```

Set environment variables:

```bash
export AGENT_ID=branch-office-01
export SERVER_WS_URL=ws://<PUBLIC_IP_OR_DNS>:8000/ws/agent
export AGENT_TOKEN=<strong-shared-token>
export REQUEST_TIMEOUT=20
export RECONNECT_SECONDS=3
```

Run agent:

```bash
PYTHONPATH=. python -m agent.main
```

---

## Public Server Setup

```bash
sudo apt update
sudo apt install -y python3 python3-venv

cd /opt
git clone <your-repo-url> bajaj-remote-gateway
cd bajaj-remote-gateway/bajaj-remote-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-server.txt
```

Set environment variables:

```bash
export AGENT_TOKEN=<strong-shared-token>
export LOG_LEVEL=INFO
```

Run FastAPI server:

```bash
PYTHONPATH=. uvicorn server.main:app --host 0.0.0.0 --port 8000
```

---

## Example Usage

Health check:

```bash
curl http://localhost:8000/health
```

Proxy camera UI (single agent connected):

```text
http://localhost:8000/proxy/192.168.1.20:80/
```

POST example:

```bash
curl -X POST \
  "http://localhost:8000/proxy/192.168.1.20:80/login?agent_id=branch-office-01" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

---

## Production Notes

- Put server behind Nginx/Caddy with HTTPS.
- Replace static token with rotated secret management.
- Add per-agent target allowlists before production rollout.
- Add request rate limiting and audit logging.
- Streaming/video endpoints can be added later via chunked or WebRTC-specific modules.
