"""Generate static paged JSON for the REA MLS Listings API (GitHub Pages).

Usage:  python generate_pages.py --base-url https://YOUR_GITHUB_USER.github.io/rea-mls-api [--version 1|2] [--out-dir DIR]
Writes: DIR/page-1.json ... page-N.json  (5,050 records, 500 per page). Default DIR = v1/listings
Version 2 (schema drift): LivingArea renamed to LivingAreaSqft, new field VirtualTourURL.
nextLink always points at the LIVE path /v1/listings/ so snapshots can be copied in place.
Planted DQ issues (~8%): null price, negative price, orphan property, duplicates, future timestamps.
"""
import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone

TOTAL_UNIQUE = 5000
DUPLICATES = 50
PAGE_SIZE = 500
SEED = 20261105

MLS = {"MLS_MIDWEST": "MW", "MLS_NORTHEAST": "NE", "MLS_GULF": "GF", "MLS_MOUNTAIN": "MT", "MLS_PACIFIC": "PC"}
STATUSES = ["Active"] * 33 + ["Sold"] * 21 + ["Expired"] * 12 + ["Withdrawn"] * 12 + ["Coming Soon"] * 11 + ["Pending"] * 11
TYPES = ["Single Family", "Single Family", "Single Family", "Condo", "Townhouse", "Multi-Family", "Land"]
CITIES = [("Phoenix", "AZ"), ("Nashville", "TN"), ("Atlanta", "GA"), ("Columbus", "OH"), ("Austin", "TX"),
          ("Denver", "CO"), ("Tampa", "FL"), ("Charlotte", "NC"), ("Seattle", "WA"), ("Boston", "MA")]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_records(rng):
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    recs = []
    for i in range(1, TOTAL_UNIQUE + 1):
        mls = rng.choice(list(MLS))
        city, st = rng.choice(CITIES)
        listed = now - timedelta(days=rng.randint(1, 700), minutes=rng.randint(0, 1440))
        modified = listed + timedelta(days=rng.randint(0, 60))
        if modified > now:
            modified = now - timedelta(hours=rng.randint(1, 48))
        recs.append({
            "ListingId": f"LST{i:07d}",
            "MlsId": mls,
            "MlsListingNumber": f"{MLS[mls]}-{1000000 + i}",
            "PropertyId": f"PROP{rng.randint(1, 500):05d}",
            "StandardStatus": rng.choice(STATUSES),
            "PropertyType": rng.choice(TYPES),
            "ListPrice": rng.randrange(150000, 2500001, 1000),
            "BedroomsTotal": rng.randint(1, 6),
            "BathroomsTotal": rng.randint(1, 5),
            "LivingArea": rng.randint(600, 5000),
            "ListingContractDate": iso(listed),
            "ModificationTimestamp": iso(modified),
            "Address": {"City": city, "StateOrProvince": st},
            "ListAgent": {"AgentId": f"AGT{rng.randint(1, 2000):06d}", "OfficeId": f"ACC{rng.randint(1, 300):05d}"},
        })

    idx = list(range(TOTAL_UNIQUE))
    rng.shuffle(idx)
    for j in idx[0:150]:
        recs[j]["ListPrice"] = None                                   # null price
    for j in idx[150:190]:
        recs[j]["ListPrice"] = -rng.randrange(10000, 900000, 1)       # negative price
    for j in idx[190:290]:
        recs[j]["PropertyId"] = "PROP_ORPHAN_99999"                   # orphan property
    for j in idx[290:339]:
        recs[j]["ModificationTimestamp"] = iso(now + timedelta(days=rng.randint(30, 400)))  # future ts

    # duplicates: same ListingId, older ModificationTimestamp, different price
    for j in rng.sample(range(TOTAL_UNIQUE), DUPLICATES):
        dup = json.loads(json.dumps(recs[j]))
        if recs[j]["ListPrice"] is not None:
            dup["ListPrice"] = abs(recs[j]["ListPrice"]) + 5000
        dup["ModificationTimestamp"] = recs[j]["ListingContractDate"]
        recs.append(dup)
    rng.shuffle(recs)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://you.github.io/rea-mls-api (no trailing slash)")
    ap.add_argument("--version", type=int, choices=[1, 2], default=1)
    ap.add_argument("--out-dir", default=os.path.join("v1", "listings"))
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    rng = random.Random(SEED)
    recs = build_records(rng)
    if args.version == 2:
        for r in recs:
            r["LivingAreaSqft"] = r.pop("LivingArea")
            r["VirtualTourURL"] = f"https://tours.example.com/{r['ListingId']}"
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    pages = (len(recs) + PAGE_SIZE - 1) // PAGE_SIZE
    for p in range(1, pages + 1):
        body = {
            "@odata.context": f"{base}/v1/$metadata#Property",
            "@odata.count": len(recs),
            "page": p,
            "pageSize": PAGE_SIZE,
            "value": recs[(p - 1) * PAGE_SIZE: p * PAGE_SIZE],
        }
        if p < pages:
            body["@odata.nextLink"] = f"{base}/v1/listings/page-{p + 1}.json"
        with open(os.path.join(out_dir, f"page-{p}.json"), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1)
    print(f"Wrote v{args.version}: {pages} pages, {len(recs)} records to {out_dir}")


if __name__ == "__main__":
    main()
