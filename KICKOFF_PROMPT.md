# Paste this as the first message in Claude Code

I'm building **When Yah?** for Dormathon 2026 (Track 1: Predictive Model). Hard submission
Sun 11 Oct 09:00 MYT. Read `CLAUDE.md` and `docs/PRD.md` first; `.claude/rules/` and `.claude/agents/`
are set up.

**Summary:** At peak hours people check Grab, inDrive and GV Ride one by one and can't tell if the price
will drop. The user types the price(s) they see; we predict how that price changes over the next 60
minutes and say book now or wait (until when), which quoted app is likely cheapest at the best time,
and which real nearby events are likely to push prices up. The model is trained and evaluated on real
public ride data (Boston Uber/Lyft; Chicago backup). **Evidence rule:** every number traces to real data
or a cited source — no invented fares, multipliers or per-app prices.

**Team:** I own data, model and API. My partner owns the visual design (`design/`) — don't invent UI
styling. Work autonomously; report what you did and what's next. Ask only for irreversible or genuinely
ambiguous decisions.

**Do now, in order (commit after each, show me the output):**
1. Scaffold the repo per `CLAUDE.md` (README, `.env.example`, `.gitignore` incl. `data/raw/`,
   `requirements.txt` with pandas, pyarrow, scikit-learn, lightgbm, joblib, fastapi, uvicorn, pydantic;
   Vite React TS app). Add `scripts/run_demo.sh`. Fill in Commands.
2. Stub `/api/forecast` and `/api/events` with the exact contract shapes (`model_version: "stub"`), so my
   partner can start the frontend now.
3. Tell me exactly where to put the Boston dataset (I'll download it). The TD Garden game schedule is
   already in `data/events/td_garden_games.csv`. Then write `ml/check_signal.py` per `.claude/rules/ml.md`, run it, and use the `signal-checker`
   agent for a GO / SWITCH recommendation before 14:00.
4. After GO: `build_dataset.py`, `features.py`, `train.py` (no-level + with-level), `evaluate.py` with
   both baselines → `reports/metrics.md`; then run the `leakage-auditor` agent.
5. Replace the stub with the real forecast (apply % change to typed quotes), `/api/events` from
   `data/events/malaysia_events.csv`, then `event_effect.py` → `reports/event_effect.md`.

Track progress against `docs/PRD.md` §7 and warn me early if the 14:00 go/no-go or the 19:00 end-to-end
checkpoint is at risk.
