# Realtor.com: MLS Listings Custom Connector, Medallion Load and Schema Drift Recovery

**Audience:** Ted Manasa (Sr Mgr Data Platform), Santosh Payal (Sr Director, Data)
**Story:** Replace Fivetran for a RESO-style MLS feed. Maia builds a custom connector from API docs, generates the bronze → silver pipelines, then detects and fixes schema drift with a person approving the change.
**Environment:** Snowflake `MTLN_SANDBOX.MAIA_GARNIE_BOLLING_1` · branch `garnie_bolling/realtor-20261105` · env `demo-garnie-bolling`

---

## 1. Setting up the custom API

### 1.1 The source: a fake RESO-style MLS API on GitHub Pages
| Item | Value |
|---|---|
| Repo | `github.com/garniebolling-maia/realtor-dot-com` |
| Docs page (Maia reads this) | `https://garniebolling-maia.github.io/realtor-dot-com/index.html` |
| Spec (upload option) | `openapi.yaml` (OpenAPI 3.0, under 5 MB) |
| Endpoint | `GET /v1/listings/page-{n}.json` (11 pages × 500 = 5,050 records) |
| Auth | None (the connector also supports API Key, Basic, Bearer and OAuth for real MLS feeds) |
| Paging | Full-URL next link (`nextLink`, plus `@odata.nextLink` for the RESO look); the last page has none |
| Payload | `{ "@odata.count", "page", "value": [ listings... ], "nextLink" }` with nested `Address{}` and `ListAgent{}` |

**Repo files**
```
index.html            API docs page
openapi.yaml          OpenAPI spec
generate_pages.py     Builds the JSON pages (--version 1|2, fixed seed)
swap.sh               ./swap.sh v1 | v2: switches the live payload, commits and pushes
snapshots/v1/*.json   Baseline payload
snapshots/v2/*.json   Drifted payload
v1/listings/*.json    LIVE payload (what the connector calls)
```

**Planted data quality issues (about 8%, same as the rest of the demo):** 150 null prices, 40 negative prices, 100 orphan properties (`PROP_ORPHAN_99999`), 49 future `ModificationTimestamp` values, 50 duplicate `ListingId`s.

### 1.2 Building the connector with Maia
1. **Custom connectors → Create with Maia**, then paste the docs URL or upload `openapi.yaml`.
2. Prompt:
   > Build a custom connector named REA MLS Listings for this API. No authentication. Import the listings endpoint starting at page 1, paginate by following the next link (absolute URL) until it is absent. Records are in `value`.
3. Resulting connector: **REA MLS Listings API**, endpoint **List Listings** (PUBLISHED).
4. Pagination tab:

| Setting | Value |
|---|---|
| Method | Full Path |
| Next page URI property | `nextLink` |
| Page size | 500 |
| Page size parameter | `pageSize` (required by the editor; GitHub Pages ignores it) |

> **Lesson learned:** `@odata.nextLink` only loaded page 1, probably because the connector treats the `.` as a JSON path separator. Adding a plain `nextLink` key fixed it: 11 pages and 5,050 records.

---

## 2. Pipelines: API → raw (bronze) → silver

### 2.1 `NEW_Load MLS Listings.orch.yaml` (orchestration)
```
Start → Extract MLS Listings → Build MLS Silver → Assert Silver Row Count
```
| Component | Type | What it does |
|---|---|---|
| Extract MLS Listings | Custom connector (REA MLS Listings API / List Listings) | Calls the API, follows `nextLink` through all 11 pages, writes **`REA_MLS_LISTINGS_RAW`** (Replace). Each page lands as one row in a VARIANT column `DATA_VALUE`. |
| Build MLS Silver | Run Transformation | Runs `NEW_MLS Listings Silver.tran.yaml` |
| Assert Silver Row Count | Assert Table | Fails the pipeline unless **`REA_MLS_LISTINGS_SILVER` has 4,000 rows or more**. This is the **drift check**. |

### 2.2 `NEW_MLS Listings Silver.tran.yaml` (transformation)
```
MLS Raw Pages → Flatten Listings ─┐
                    Property ─────┴→ Match Property → Dedupe Rank → DQ Rules ─┬→ Valid Listings    → Write Silver   (REA_MLS_LISTINGS_SILVER)
                                                                              └→ Rejected Listings → Write Rejected (REA_MLS_LISTINGS_REJECTED)
```
| Component | Type | Logic |
|---|---|---|
| MLS Raw Pages | Table Input | `REA_MLS_LISTINGS_RAW.DATA_VALUE` |
| Flatten Listings | Flatten Variant | Flattens `value[]`, one row per listing, and maps the fields (including `Address.City` and `ListAgent.AgentId`). **`LivingArea` → `LIVING_SQFT`.** |
| Property | Table Input | `REA_RE_PROPERTY.PROPERTY_ID` |
| Match Property | Join (Left) | Adds `MATCHED_PROPERTY_ID`; NULL means an orphan |
| Dedupe Rank | Rank (Row Number) | Partition by `LISTING_ID`, order by `MODIFIED_AT` desc gives `RN` |
| DQ Rules | Calculator | Sets `REJECTION_REASON`, then `DW_LOAD_DATE`, `DW_SOURCE`, `DW_BATCH_ID` |
| Valid / Rejected Listings | Filter | Reason is NULL → silver; NOT NULL → rejected |
| Write Silver / Write Rejected | Rewrite Table | Idempotent CREATE OR REPLACE |

**DQ rule order (first match wins):**
1. `LIVING_SQFT IS NULL` → `SCHEMA_DRIFT_LIVING_SQFT_MISSING`
2. `RN > 1` → `DUPLICATE_LISTING_ID`
3. `LIST_PRICE IS NULL` → `NULL_LIST_PRICE`
4. `LIST_PRICE < 0` → `NEGATIVE_PRICE`
5. No property match → `ORPHAN_PROPERTY_ID`
6. `MODIFIED_AT` in the future → `FUTURE_TIMESTAMP`

### 2.3 v1 baseline results (green run)
| Table | Rows |
|---|---|
| `REA_MLS_LISTINGS_RAW` | 11 (pages) holding 5,050 listings |
| `REA_MLS_LISTINGS_SILVER` | **4,661** |
| `REA_MLS_LISTINGS_REJECTED` | **389**: NULL_LIST_PRICE 150 · ORPHAN_PROPERTY_ID 100 · DUPLICATE_LISTING_ID 50 · FUTURE_TIMESTAMP 49 · NEGATIVE_PRICE 40 |
| Reconciliation | 4,661 + 389 = **5,050** ✅ |

---

## 3. Schema drift scenario (v2)

Running `./swap.sh v2` changes the payload served at the **same URL** the connector already calls. The connector itself is unchanged.

| Change | Type | v1 field | v2 field |
|---|---|---|---|
| Rename | **Breaking** | `LivingArea` | `LivingAreaSqft` |
| New field | Additive | none | `VirtualTourURL` |

**What we expect at each table:**
| Table | Expected v2 behaviour |
|---|---|
| `REA_MLS_LISTINGS_RAW` | **Loads successfully**, 11 rows and 5,050 listings. The raw VARIANT column takes any JSON shape, so the extract step does **not** fail. The drift arrives without any error. |
| Flatten Listings (in the silver transformation) | Still maps `LivingArea`, which no longer exists, so **`LIVING_SQFT` is NULL for every row**. `VirtualTourURL` is ignored because it isn't mapped. |
| `REA_MLS_LISTINGS_REJECTED` | **About 5,050 rows**, nearly all `SCHEMA_DRIFT_LIVING_SQFT_MISSING` |
| `REA_MLS_LISTINGS_SILVER` | **About 0 rows** |
| Assert Silver Row Count | **FAILS** (0 is below 4,000), so the pipeline status is **FAILED** |

> **Honest positioning:** custom connectors do **not** heal themselves when the source changes. Here, Matillion detects the drift through an explicit data quality rule and assert, explains it, and Maia proposes the fix. A person reviews, commits and publishes. Compare that with silent, unpredictable behaviour in Fivetran.

---

## 4. Fixing it with "Fix with Maia"

> ⚠️ **Prerequisite:** Fix with Maia is **only available for scheduled or API-triggered runs**, not manual runs from the canvas. Publish the branch to the environment and run it from a **schedule**. Use a dedicated Fix-with-Maia branch, as with the existing Agent Ops drift demo.

### 4.1 Pre-demo prep
1. Get a green v1 run: commit, then **checkpoint** ("Post MLS v1 baseline").
2. `./swap.sh v2`, then confirm it's live:
   `curl -s https://garniebolling-maia.github.io/realtor-dot-com/v1/listings/page-1.json | grep -o '"LivingAreaSqft"' | head -1`
3. Publish and **schedule** `NEW_Load MLS Listings` once. It should **FAIL** at *Assert Silver Row Count*.
4. **Checkpoint** ("Pre Fix-with-Maia, MLS drift"), keeping the failure in place.

### 4.2 Live demo (about 3 minutes)
1. Open **Pipeline Runs**, then the failed `NEW_Load MLS Listings` run.
2. In the **Troubleshoot with Maia** card, click **See more**. Maia's root cause analysis should trace the failure back from the assert to the source field rename (`LivingArea` → `LivingAreaSqft`).
3. Click **Fix with Maia**, enter a new branch name (e.g. `fix/mls-livingarea-drift`), choose base branch and environment, and Designer opens.
4. Expected fix in `NEW_MLS Listings Silver.tran.yaml` → **Flatten Listings**:
   - `LivingAreaSqft` → `LIVING_SQFT` (or `COALESCE` of both, so v1 and v2 both work)
   - New mapping `VirtualTourURL` → `VIRTUAL_TOUR_URL`
5. **Review the diff** against the original, then commit, push and open a PR. The SOX audit trail needs business-owner approval before prod.
6. Rerun: silver is back to about 4,661, rejected about 389, and the assert passes ✅.

**Talking points**
- Maia found the *originating* cause (a source field rename), not just the symptom (an assert failing on row count).
- The fix is a reviewable git diff, not a silent auto-change.
- The custom connector endpoint can optionally be updated too, so its response schema documents `LivingAreaSqft`. That's a manual edit in the connector editor.

---

## 5. Where to find the error

| Where | What you'll see |
|---|---|
| **Pipeline Runs → failed run** | Status FAILED on `NEW_Load MLS Listings`, plus the **Troubleshoot with Maia** card |
| **Run details (per component)** | Extract ✅ (11 rows) · Build MLS Silver ✅ · **Assert Silver Row Count ❌**, with the assertion message (row count 0, expected at least 4,000) |
| **Designer → Task history → double-click run → Logging tab** | Step-by-step logs and generated SQL for each component |
| **Snowflake (evidence)** | See the queries below |

```sql
-- Why silver is empty
SELECT REJECTION_REASON, COUNT(*)
FROM MTLN_SANDBOX.MAIA_GARNIE_BOLLING_1.REA_MLS_LISTINGS_REJECTED
GROUP BY 1 ORDER BY 2 DESC;              -- SCHEMA_DRIFT_LIVING_SQFT_MISSING ~5,050

-- Proof the source renamed the field
SELECT f.value:"LivingArea" AS v1_field, f.value:"LivingAreaSqft" AS v2_field, f.value:"VirtualTourURL" AS new_field
FROM MTLN_SANDBOX.MAIA_GARNIE_BOLLING_1.REA_MLS_LISTINGS_RAW r,
     LATERAL FLATTEN(input => r.DATA_VALUE:"value") f
LIMIT 5;                                  -- v1_field NULL, v2_field populated
```

---

## 6. Reset
| Goal | Action |
|---|---|
| Demo again (keep the failure) | Restore checkpoint "Pre Fix-with-Maia, MLS drift"; leave v2 live; delete the fix branch |
| Full reset to v1 | `./swap.sh v1`, then restore checkpoint "Post MLS v1 baseline" |
