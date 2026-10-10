---
paths:
  - "web/**"
  - "design/**"
---

# Frontend rules — When Yah?

- Partner owns the visual design. Follow `design/` exactly; never invent layouts, colours, fonts or copy
  styles. If `design/` is empty, build plain unstyled components that only wire API data.
- Screens and what they must show: `docs/PRD.md` §6.
- The quote box is labelled **"Masukkan harga yang anda nampak"** (app + RM, one or more). Optional
  field **"harga biasa"** (usual price).
- Show RM values only for apps the user quoted; otherwise show percentages.
- Every number has a visible source: "your price", "model (tested on real ride data)", or the event's source link.
- Demo presets use example quotes labelled "example".
- Location: "Use my location" requests browser geolocation once, with permission; never stored.
- Use "predict"/"ramal" wording; never claim a live connection to Grab, inDrive or GV Ride.
