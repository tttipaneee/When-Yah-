# Signal check (go/no-go) — 10 Oct 2026

All numbers below were computed by scripts on real public data. Price index = actual fare ÷ expected fare
for that trip's distance and duration (linear fit per company, training days only).

## Boston, MA (Kaggle "Uber and Lyft Dataset Boston, MA") — **NO-GO**
- Uber `surge_multiplier` is always 1.0; Lyft surge > 1 on 6.8% of rides, flat across hours.
- Hour × weekday explains 0.14% of index variance (R² 0.0014); lag autocorrelation ≈ 0.
- UberX price per mile is flat by hour.
- TD Garden game nights vs non-game nights: Lyft surge share 4.4% vs 4.1% (no effect).
- Collection has coverage gaps between timestamps.

## NYC TLC High Volume FHV, Aug 2024 — **GO (modest)**
Command: `python ml/check_signal_nyc.py data/raw/fhvhv_tripdata_2024-08.parquet`
```
rows=19,128,392 days=33 2024-07-31 .. 2024-09-01 train_cut=2024-08-23
HV0003: fare ~ 3.28 + 2.53*miles + 0.51*min (train days)
HV0005: fare ~ 3.99 + 2.06*miles + 0.54*min (train days)
zone x 15-min windows with >= 8 trips: 547,294 across 254 zones
variance of zone index explained by hour x weekday: 0.045
+15 min: lag corr=0.440  share changing >=10%=0.150  persistence MAE=0.0557
+30 min: lag corr=0.368  share changing >=10%=0.163  persistence MAE=0.0586
+60 min: lag corr=0.307  share changing >=10%=0.173  persistence MAE=0.0612
+30 min test MAE: persistence=0.0558  hour-avg=0.0910  simple model=0.0531  (n=143,919)
```
Index is lowest around midnight (~0.95) and highest midday (~1.01).

## Reading
- Prices do move: 15–17% of zone windows change ≥10% within 15–60 min, and the current level carries
  information (lag corr 0.31–0.44), so "wait or book" is a meaningful question.
- Time of day alone explains little (4.5%). The current level (from the user's usual price) is the key input.
- A simple model beats persistence by ~5% MAE at +30 min. The gain is real but modest; pitch it honestly.
- Caveat: zone index is a 15-min average of many trips; a single user's quote is noisier.
