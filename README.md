# When Yah?

Dormathon 2026 · Track 1: Predictive Model ("Predict Early, Decide Better").

At peak hours, should you book your ride now or wait? Type the price you see in Grab, inDrive or
GV Ride, and When Yah? predicts how it will change over the next 60 minutes, tells you when to book,
which of your quoted apps is likely cheapest then, and which real events nearby may push prices up.

Every number traces to real data or a cited source: the model is trained and tested on public
ride-hailing data; prices come from what you type. Not connected to Grab, inDrive or GV Ride.

## Start here
- `docs/PRD.md` — requirements, timeline split between the two of us, demo script, cut list
- `CLAUDE.md` — instructions Claude Code reads every session
- `.claude/rules/`, `.claude/agents/` — module rules and review helpers
- `design/` — screen designs (Partner)
- `KICKOFF_PROMPT.md` — first message to paste into Claude Code

## Run it
```bash
pip install -r requirements.txt && (cd web && npm install)   # setup (Python 3.11+, Node 20+)
scripts/run_demo.sh                                           # API :8000 + web :5173
python -m pytest -q tests                                     # API contract tests
```
`/api/forecast` is a **stub** (`model_version: "stub"`, placeholder percentages) until the model passes
evaluation in `reports/metrics.md`. RM values are always the user's typed quote × predicted % change.
