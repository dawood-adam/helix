# Guide 6 — Background enrichment (Watcher) & the mobile/QR web view

**Goal:** run the async Watcher (off by default) so new papers are
passively ingested to Notes and surfaced as FYI proposals you accept on
your terms; and pair the zero-dependency web view for one-tap gate
resolution from a phone/browser.

**Prerequisites:** install per [getting-started](../getting-started.md);
offline.

```bash
export HELIX_HOME=/tmp/g6 HELIX_EXPLORE_BACKEND=fake HELIX_AGENTS=fake
helix setup --model anthropic:claude-sonnet-4.6        # (output omitted)
```

## Part A — the Watcher

The Watcher proposes a diff against an existing **canonical** concept,
so seed one first (no CLI verb creates a canonical concept directly —
salvage or the API does; here, the API):

```text
$ python -c "from helix.app import Helix; from helix.atlas.writequeue import Intent; \
Helix().wq.submit(Intent(op='create', payload={'type':'concept', \
'title':'Centerline Tracing','status':'canonical','summary':'centerline tracing', \
'body':'centerline tracing in tubular anatomy'}))"

$ helix watcher status
enabled: False  schedule: None
watching: (active projects only)
seen papers: 0  open proposals: 0

$ helix watcher schedule "0 7 * * *"
Watcher enabled. Add this to your crontab (Helix does not daemonize itself):
  0 7 * * *  cd $PWD && helix watcher run   # Helix Watcher

$ helix watcher watch "centerline tracing"
watching: 'centerline tracing'

$ helix watcher run
Watcher pass: 6 new source(s) → scratch, 6 proposal(s) (0 deferred), 0 already seen.
  scratch-only; proposals are FYI until accepted (§6.4.1)

$ helix
... (badge/triage) ...
FYI (1)
  · Watcher: 6 new paper(s) may overlap centerline tracing
      → helix watcher

$ helix watcher apply w-20260517T053452-0
linked src:2026-1-centerline-tracing-study-1 into concept:centerline-tracing

$ helix watcher status
... seen papers: 6  open proposals: 5
```

**Notes:**

- **Off by default.** `helix watcher run` is a no-op until
  `helix watcher schedule …` enables it; Helix prints the crontab line
  to install and **does not daemonize itself** (honest — it's a
  separate user-cron process).
- **Scratch-only, never behind an in-flight project.** Ingested papers
  land in Notes (`scratch`) only; proposals are **FYI until you
  `apply`** (one batched line, never per-paper pings). Applying folds
  the source into the canonical concept — *blocked* if the project is
  privacy-strict or mid-workflow (§6.4.1/§9.9).
- With the offline `fake` backend, paper ids aren't query-specific, so
  a second watched scope dedupes ("already seen"); real arXiv returns
  distinct ids. With **no** canonical concept, a run still ingests to
  scratch but yields **0 proposals** (overlap needs a canonical page)
  — expected, not a bug.

## Part B — the mobile/QR web view

`helix serve` blocks (it runs the server). The runnable, scriptable
form is the same API the CLI uses:

```text
$ python - <<'PY'
import threading, urllib.request, urllib.error, json
from helix.app import Helix
from helix.web import serve
app = Helix()                                  # HELIX_HOME=/tmp/g6
httpd, url, token = serve(app, port=0)         # 0 = ephemeral port
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = url.split("/?")[0]
print(json.loads(urllib.request.urlopen(f"{base}/queue?t={token}").read()))
try:
    urllib.request.urlopen(f"{base}/queue")    # no token
except urllib.error.HTTPError as e:
    print("no-token →", e.code)
httpd.shutdown()
PY
{'NEEDS YOU NOW': [...], 'WORKING': [], 'FYI': [...]}
no-token → 403
```

Or interactively: `helix serve --port 8765`, then open the printed
`http://127.0.0.1:8765/?t=<token>` URL (an ASCII QR renders if the
optional `qrcode` package is installed; otherwise the URL/token work
as-is). Routes (see [reference/web.md](../reference/web.md)):
`GET /queue` (buckets JSON), `GET /gate/<project>` (pending gate),
`POST /resolve` (`project`,`option`,`why` form → resume the workflow).
Missing/wrong token → `403`.

> **Security:** the token is **advisory (a loopback dev tool), not a
> security boundary** — do not expose to untrusted networks.

## Common variations

- `helix watcher off` disables it; `helix watcher status` shows
  schedule, watched topics, seen count, and open proposals.
- A pending gate makes `GET /gate/<p>` and `POST /resolve` meaningful:
  run [Guide 1](01-first-project.md) steps, then resolve the gate over
  HTTP instead of the CLI.
