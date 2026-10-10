#!/usr/bin/env bash
# Download NYC TLC High Volume FHV trips, Aug 2024 -> data/raw/ and verify it.
# Official source: https://d37ci6vzbqgysf.cloudfront.net/trip-data/fhvhv_tripdata_2024-08.parquet
# (linked from https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page). If the official host is
# unreachable, falls back to a byte-identical mirror; the sha256 check below guarantees the same file.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw
F=data/raw/fhvhv_tripdata_2024-08.parquet
SHA=99fd2913d2c8935e4c1d166f229290a90971b6564c490a8ba2a257de9e08fae2
OFFICIAL=https://d37ci6vzbqgysf.cloudfront.net/trip-data/fhvhv_tripdata_2024-08.parquet
MIRROR=https://huggingface.co/datasets/DinoPonjevic/NYC_TaxiData_RAW/resolve/main/2024/fhvhv/fhvhv_tripdata_2024-08.parquet
if [ ! -f "$F" ]; then
  curl -fsSL -o "$F" "$OFFICIAL" || curl -fsSL -o "$F" "$MIRROR"
fi
echo "$SHA  $F" | sha256sum -c -
python -I -c "import pyarrow.parquet as pq; m=pq.ParquetFile('$F'); print(f'rows={m.metadata.num_rows:,} row_groups={m.num_row_groups}')"
