---
paths:
  - "web/**"
  - "design/**"
---

# Frontend rules — When Yah?

- Partner owns the visual design. Follow `design/` exactly; never invent layouts, colours, fonts or copy
  styles. If `design/` is empty, build plain unstyled components that only wire API data.
- Screens and what they must show: `docs/PRD.md` §6.
- The quote box is labelled **"Enter the prices you see"** (app + RM, one or more). Optional
  field **"Usual price (optional)"** and a **Rain** toggle.
- Show RM values only for apps the user quoted; otherwise show percentages.
- Every number has a visible source: "your price", "model (tested on real ride data)", or the event's source link.
- Demo presets use example quotes labelled "example".
- Location: "Use my location" requests browser geolocation once, with permission; never stored.
- App copy is in English. Never mention NYC / New York in the main UI; the data source is named only in the
  footer ("Trained and tested on 19M real ride-hailing trips (NYC TLC …)"). Use "predict" wording; never claim a live connection to Grab, inDrive or GV Ride.
