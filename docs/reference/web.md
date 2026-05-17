# Reference — Web gate view (`src/helix/web.py`)

A zero-dependency stdlib `http.server` exposing the queue and one-tap
gate resolution, gated by a paired token (§11, §7.7.3). Started by
`helix serve`. **Token auth is advisory (a loopback dev tool), not a
security boundary** — do not expose to untrusted networks.

## Auth

Every request must carry the pairing token as query parameter `t`
(e.g. `?t=<token>`). The token is created once at
`$HELIX_HOME/atlas/.helix/web-token` and reused. Compared with
`secrets.compare_digest`. Missing/wrong token → `403` JSON
`{"error": "bad or missing token …"}`. All responses are
`application/json` (pretty-printed).

## Routes

### `GET /` · `GET /queue`
Returns the collected queue as JSON keyed by bucket.

- **Auth:** required.
- **Response 200:** `{"NEEDS YOU NOW": [...], "WORKING": [...], "FYI": [...]}` where each item is `{"title": str, "detail": str, "command": str}` (same providers as the CLI `_build_queue`).
- **Errors:** `403` (token).
- **Example:**
  ```bash
  curl "http://127.0.0.1:8765/queue?t=$TOKEN"
  ```

### `GET /gate/<project>`
The pending workflow state for a project (`WorkflowEngine.pending`).

- **Auth:** required.
- **Response 200:** the pending dict — `{"status": "interrupted", "gate": {…}}`, or `{"status": "running"|"done", …}`.
- **Errors:** `403` (token); `404` `{"error": "<message>"}` if the project/workflow can't be inspected.
- **Example:**
  ```bash
  curl "http://127.0.0.1:8765/gate/bowel-length?t=$TOKEN"
  ```

### `POST /resolve`
Resolves the pending gate (`WorkflowEngine.resume`).

- **Auth:** required (query `?t=`).
- **Body:** URL-encoded form: `project`, `option`, optional `why`.
- **Response 200:** the new pending/status dict (next gate, `running`, or `done`).
- **Errors:** `403` (token); `400` `{"error": "<message>"}` on resume failure (e.g. unknown project, teach-back required but missing — surfaced as the exception text).
- **Example:**
  ```bash
  curl -X POST "http://127.0.0.1:8765/resolve?t=$TOKEN" \
       --data "project=bowel-length&option=approve&why=looks+right"
  ```

Unknown paths/methods → `404 {"error": "not found"}`.

## `serve(app, *, host="127.0.0.1", port=8765, once=False)`

Builds the handler bound to `app` + the paired token and constructs a
`ThreadingHTTPServer`.

- **Parameters:** `app` (`helix.app.Helix`); `host`, `port` (use `0` for an ephemeral port — useful in tests); `once` — *currently has no effect on the return value or server* (see TODO below).
- **Returns:** `(httpd, url, token)` — `httpd` is a `ThreadingHTTPServer` the caller drives (`serve_forever()` for a blocking server, or `handle_request()` / a daemon thread in tests); `url` is `http://<host>:<actual_port>/?t=<token>`; `token` is the pairing token.
- **Errors:** none raised directly; `OSError` propagates if the port is unavailable.
- **Example (test-style, ephemeral port):**
  ```python
  from helix.app import Helix
  from helix.web import serve
  import threading, urllib.request, json
  app = Helix(home="/tmp/h")
  httpd, url, token = serve(app, port=0)
  threading.Thread(target=httpd.serve_forever, daemon=True).start()
  base = url.split("/?")[0]
  print(json.loads(urllib.request.urlopen(f"{base}/queue?t={token}").read()))
  httpd.shutdown()
  ```
