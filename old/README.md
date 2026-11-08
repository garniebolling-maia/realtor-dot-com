# REA MLS Listings API (GitHub Pages demo)

A static, no-login, RESO-style listings API used to demo Maia building a custom connector from docs or a spec.

## Publish (about 10 minutes)
1. Create a public GitHub repo named `rea-mls-api`.
2. Copy `index.html`, `openapi.yaml` and `generate_pages.py` into the repo root.
3. Replace `YOUR_GITHUB_USER` in `index.html` and `openapi.yaml` with your GitHub username.
4. Run: `python generate_pages.py --base-url https://YOUR_GITHUB_USER.github.io/rea-mls-api` (writes `v1/listings/page-1..11.json`).
5. Add an empty `.nojekyll` file, then commit and push.
6. Settings → Pages → Deploy from branch → `main` / root.
7. Check that `https://YOUR_GITHUB_USER.github.io/rea-mls-api/v1/listings/page-1.json` loads. Do this well before the demo, because Pages can take a few minutes to update.

## Demo prompt (custom connector)
Path A, docs URL: give Maia `https://YOUR_GITHUB_USER.github.io/rea-mls-api/index.html`.
Path B, spec upload: upload `openapi.yaml`.

Suggested prompt:
> Build a custom connector for the REA MLS Listings API. It needs no authentication. Import the listings endpoint, starting at page 1, and paginate by following `@odata.nextLink`, which is an absolute URL, until it is absent. Records are in `value`.

## Data
5,050 records: 5,000 unique listings plus 50 duplicates. The IDs match Snowflake (`LST…`, `PROP00001–00500` → `REA_RE_PROPERTY`).
Planted issues: 150 null prices, 40 negative prices, 100 `PROP_ORPHAN_99999` properties, 49 future `ModificationTimestamp` values, 50 duplicate `ListingId`s.

## Schema drift demo (Fix with Maia, v2 pre-loaded)
The connector is built on v1 and always calls `/v1/listings/page-{n}.json`. We change what that URL serves.

One-time setup (BASE = https://garniebolling-maia.github.io/realtor-dot-com):
```
python3 generate_pages.py --base-url $BASE --version 1 --out-dir snapshots/v1
python3 generate_pages.py --base-url $BASE --version 2 --out-dir snapshots/v2
chmod +x swap.sh
./swap.sh v1
```
v2 = `LivingArea` renamed `LivingAreaSqft` (breaking) + new `VirtualTourURL` (additive).

Pre-demo prep (about 10 minutes before the call):
1. `./swap.sh v1` → run `NEW_Load MLS Listings` → green baseline → checkpoint.
2. `./swap.sh v2` → wait for Pages → run again → the Assert fails (LIVING_SQFT is all null) → checkpoint "Pre Fix-with-Maia MLS drift".

Live (about 3 minutes): open the failed run → Fix with Maia → review the proposed connector and silver mapping change plus the git diff → rerun green.

Reset: restore the checkpoint and keep v2 live (ready to demo again), or `./swap.sh v1` for a full reset.

## Caveats to say honestly
- Static hosting means query filters are ignored, so every load is a full reload.
- No login is shown here; custom connectors support API Key, Basic, Bearer and OAuth for real MLS feeds.
- Backup source if the site is down: `REA_MLS_LISTINGS` in Snowflake.
