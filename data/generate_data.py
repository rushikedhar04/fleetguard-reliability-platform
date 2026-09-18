"""
Synthetic data generator for FleetGuard.

Produces four raw CSVs into data/raw/, simulating four disconnected source
systems for the same fleet of assets:

  - asset_registry_raw.csv   (master data / "crosswalk" source — asset_id,
                               model, and the raw identifiers each other
                               system uses)
  - service_tickets_raw.csv  (human-entered, messy)
  - telemetry_raw.csv        (high-volume sensor readings)
  - warranty_claims_raw.csv  (structured, different ID + component taxonomy)

The messiness is injected deliberately and is documented inline next to each
injection point, so the "raw" files look like something a real technician,
sensor gateway, and claims system would actually produce — not a clean
CSV with noise sprinkled on top.

Key design choice: asset_registry_raw.csv is treated as its own (imperfect)
source, not a ready-made crosswalk. IDs in the transactional tables
(tickets/telemetry/claims) are formatted inconsistently relative to how the
registry stores them (case, dashes, prefixes) — so building `asset_crosswalk`
downstream requires real normalization/matching logic, not a plain join.
"""
import os
import random
import string
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

OUT_DIR = os.path.join(os.path.dirname(__file__), "raw")
os.makedirs(OUT_DIR, exist_ok=True)

N_ASSETS = 6000
N_TICKETS = 22000
N_CLAIMS = 3200
SIM_START = datetime(2023, 1, 1)
SIM_END = datetime(2025, 6, 30)

MODELS = [
    "FleetMax 3000",
    "TerraHaul X2",
    "CoreDrive 500",
    "PowerUnit Alpha",
    "UrbanTrans 7",
    "HeavyLift Pro",
]

# Canonical component taxonomy, as used by service technicians.
COMPONENTS = [
    "Brake Pad",
    "Fuel Injector",
    "Cooling Fan",
    "Battery Pack",
    "Sensor Module",
    "Transmission",
    "Alternator",
    "Compressor",
    "Hydraulic Pump",
    "Exhaust Valve",
]

# Deliberate mismatch: warranty claims use a different internal taxonomy code
# for the same physical components. This is exactly the kind of mismatch the
# reconciliation layer is supposed to catch, not silently paper over.
COMPONENT_TAXONOMY_MAP = {
    "Brake Pad": "brake_assembly",
    "Fuel Injector": "fuel_system",
    "Cooling Fan": "cooling_unit",
    "Battery Pack": "battery_module",
    "Sensor Module": "sensor_pkg",
    "Transmission": "drivetrain",
    "Alternator": "electrical_charging",
    "Compressor": "hvac_compressor",
    "Hydraulic Pump": "hydraulics",
    "Exhaust Valve": "emissions_valve",
}
# A code warranty claims sometimes use that has NO mapping back to the
# service-ticket taxonomy at all — an unresolvable taxonomy mismatch.
UNMAPPED_CLAIM_CODES = ["misc_repair", "unclassified"]

RESOLUTION_CODES = ["Repaired", "Replaced", "Adjusted", "No Fault Found", "Pending Parts"]
RESOLUTION_TYPOS = {  # inconsistent casing / typos injected into raw tickets
    "Repaired": ["repaired", "REPAIRED", "Repaird"],
    "Replaced": ["replaced", "Replacd", "REPLACED"],
    "Adjusted": ["adjusted", "Adjustd"],
    "No Fault Found": ["no fault found", "NFF", "No fault found"],
    "Pending Parts": ["pending parts", "Pending Part"],
}


def random_date(start, end):
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def fmt_date_messy(dt):
    """Return a date string in one of several inconsistent formats."""
    fmt = random.choice(["%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S"])
    return dt.strftime(fmt)


def make_vin():
    alphabet = string.ascii_uppercase.replace("I", "").replace("O", "").replace("Q", "") + string.digits
    return "".join(random.choices(alphabet, k=17))


def messify_id(raw_id, kind):
    """Apply realistic formatting noise to an identifier as it would appear
    in a transactional system, relative to how the registry stores it."""
    r = random.random()
    if kind == "vin_or_unit_no":
        if raw_id.startswith("UNIT-"):
            if r < 0.3:
                return raw_id.replace("UNIT-", "unit").lower()
            return raw_id
        # VIN case: sometimes bare VIN, sometimes VIN- prefixed, sometimes lowercase
        if r < 0.4:
            return raw_id
        elif r < 0.7:
            return f"VIN-{raw_id}"
        else:
            return raw_id.lower()
    if kind == "device_id":
        if r < 0.5:
            return raw_id
        elif r < 0.8:
            return raw_id.replace("DEV-", "")
        else:
            return raw_id.replace("DEV-", "dev_")
    if kind == "asset_serial":
        if r < 0.6:
            return raw_id
        elif r < 0.85:
            return raw_id.replace("SN-", "")
        else:
            return raw_id.lower()
    return raw_id


def build_asset_registry():
    rows = []
    for i in range(1, N_ASSETS + 1):
        asset_id = f"AST-{i:05d}"
        model = random.choice(MODELS)
        in_service = random_date(SIM_START, SIM_START + timedelta(days=180))
        if random.random() < 0.7:
            vin_or_unit_no = make_vin()
        else:
            vin_or_unit_no = f"UNIT-{random.randint(1000, 9999)}"
        device_id = f"DEV-{i:06d}"
        asset_serial = "SN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        rows.append(
            {
                "asset_id": asset_id,
                "model": model,
                "in_service_date": in_service.strftime("%Y-%m-%d"),
                "vin_or_unit_no": vin_or_unit_no,
                "device_id": device_id,
                "asset_serial": asset_serial,
            }
        )
    return pd.DataFrame(rows)


def build_service_tickets(registry):
    rows = []
    assets = registry.to_dict("records")
    for i in range(1, N_TICKETS + 1):
        ticket_id = f"TCK-{i:06d}"
        asset = random.choice(assets)
        component = random.choice(COMPONENTS)
        reported = random_date(
            datetime.strptime(asset["in_service_date"], "%Y-%m-%d"), SIM_END
        )

        symptom = random.choice(
            [
                "customer reports unusual noise",
                "warning light triggered on dash",
                "unit failed to start",
                "overheating observed during operation",
                "fluid leak noticed by driver",
                "reduced performance under load",
                "intermittent fault, hard to reproduce",
            ]
        )
        notes = (
            f"{symptom}. Inspected and found issue related to {component.lower()}. "
            f"{random.choice(['Ordered replacement part.', 'Serviced on site.', 'Escalated to depot.', 'Monitored, no further action.'])}"
        )

        # ~15% missing component_flagged — technician forgot to fill it in
        component_flagged = None if random.random() < 0.15 else component

        resolution_code = random.choice(RESOLUTION_CODES)
        if random.random() < 0.4:
            resolution_code = random.choice(RESOLUTION_TYPOS[resolution_code])

        rows.append(
            {
                "ticket_id": ticket_id,
                "vin_or_unit_no": messify_id(asset["vin_or_unit_no"], "vin_or_unit_no"),
                "reported_date": fmt_date_messy(reported),
                "technician_notes": notes,
                "component_flagged": component_flagged,
                "resolution_code": resolution_code,
                "_true_asset_id": asset["asset_id"],  # kept only for duplicate/orphan injection below
                "_true_component": component,
                "_true_date": reported,
            }
        )

    df = pd.DataFrame(rows)

    # Inject a handful of duplicate events: same asset+component+date re-logged
    # as a second ticket (simulates a technician re-opening or double-entry).
    dup_sample = df.sample(n=min(80, len(df)), random_state=SEED).copy()
    dup_sample["ticket_id"] = [f"TCK-DUP-{i:04d}" for i in range(len(dup_sample))]
    dup_sample["reported_date"] = dup_sample["_true_date"].apply(
        lambda d: fmt_date_messy(d + timedelta(days=random.choice([0, 1])))
    )
    df = pd.concat([df, dup_sample], ignore_index=True)

    lineage_cols = ["_true_asset_id", "_true_component", "_true_date"]
    lineage = df[["ticket_id"] + lineage_cols].copy()
    public = df.drop(columns=lineage_cols)
    return public, lineage


def build_telemetry(registry):
    rows = []
    assets = registry.to_dict("records")
    for asset in assets:
        in_service = datetime.strptime(asset["in_service_date"], "%Y-%m-%d")
        weeks = max(1, int((SIM_END - in_service).days / 7))
        # 1-3 readings/week, asset skips some weeks (sensor downtime) — keeps
        # volume realistic without simulating true high-frequency IoT.
        n_readings = int(weeks * random.uniform(1.0, 3.0) * random.uniform(0.6, 1.0))
        base_temp = random.uniform(55, 75)
        base_vib = random.uniform(0.2, 0.8)
        runtime = 0.0
        for _ in range(n_readings):
            ts = random_date(in_service, SIM_END)
            runtime += random.uniform(2, 20)
            temp = np.random.normal(base_temp, 4)
            vib = max(0.0, np.random.normal(base_vib, 0.15))
            error_code = None
            if random.random() < 0.04:
                error_code = f"E{random.randint(100, 599)}"
                temp += random.uniform(5, 15)
                vib += random.uniform(0.3, 1.0)

            # ~2% out-of-range sensor glitches (physically implausible values)
            if random.random() < 0.02:
                temp = random.choice([-999.0, 450.0, np.nan])
            if random.random() < 0.02:
                vib = random.choice([-5.0, 99.9])

            rows.append(
                {
                    "device_id": messify_id(asset["device_id"], "device_id"),
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "temperature_c": round(float(temp), 2) if temp == temp else None,  # keep NaN as null
                    "vibration_index": round(float(vib), 3),
                    "error_code": error_code,
                    "runtime_hours_cumulative": round(runtime, 1),
                }
            )
    df = pd.DataFrame(rows)
    return df.sort_values("timestamp").reset_index(drop=True)


def build_warranty_claims(registry, tickets_lineage):
    rows = []
    assets = registry.to_dict("records")

    # Most claims are backed by a real service ticket on the same asset —
    # this is what makes them "supported" in reconciliation.
    supported = tickets_lineage.sample(n=int(N_CLAIMS * 0.75), random_state=SEED, replace=True)
    asset_by_id = {a["asset_id"]: a for a in assets}

    i = 0
    for _, t in supported.iterrows():
        i += 1
        asset = asset_by_id[t["_true_asset_id"]]
        claim_date = t["_true_date"] + timedelta(days=random.randint(1, 21))
        component = t["_true_component"]
        claim_component = COMPONENT_TAXONOMY_MAP.get(component, random.choice(UNMAPPED_CLAIM_CODES))
        rows.append(_claim_row(i, asset, claim_date, claim_component))

    # The rest are orphaned claims: no corresponding ticket/telemetry event
    # anywhere. This is the "trust problem" the DQ layer must surface.
    n_orphan = N_CLAIMS - len(rows)
    for _ in range(n_orphan):
        i += 1
        asset = random.choice(assets)
        claim_date = random_date(datetime.strptime(asset["in_service_date"], "%Y-%m-%d"), SIM_END)
        claim_component = random.choice(list(COMPONENT_TAXONOMY_MAP.values()) + UNMAPPED_CLAIM_CODES)
        rows.append(_claim_row(i, asset, claim_date, claim_component))

    df = pd.DataFrame(rows)
    return df.sample(frac=1, random_state=SEED).reset_index(drop=True)


def _claim_row(i, asset, claim_date, claim_component):
    return {
        "claim_id": f"CLM-{i:06d}",
        "asset_serial": messify_id(asset["asset_serial"], "asset_serial"),
        "claim_date": claim_date.strftime("%Y-%m-%d"),
        "component_claimed": claim_component,
        "claim_amount": round(random.uniform(150, 8500), 2),
        "claim_status": random.choices(
            ["approved", "denied", "pending"], weights=[0.65, 0.15, 0.2]
        )[0],
    }


def main():
    print("Generating asset registry...")
    registry = build_asset_registry()
    registry.drop(columns=["in_service_date"]).to_csv(
        os.path.join(OUT_DIR, "asset_registry_raw.csv"), index=False
    )
    # keep in_service_date available in-memory for downstream generation
    registry_full = registry.copy()

    print("Generating service tickets...")
    tickets, tickets_lineage = build_service_tickets(registry_full)
    tickets.to_csv(os.path.join(OUT_DIR, "service_tickets_raw.csv"), index=False)

    print("Generating telemetry...")
    telemetry = build_telemetry(registry_full)
    telemetry.to_csv(os.path.join(OUT_DIR, "telemetry_raw.csv"), index=False)

    print("Generating warranty claims...")
    claims = build_warranty_claims(registry_full, tickets_lineage)
    claims.to_csv(os.path.join(OUT_DIR, "warranty_claims_raw.csv"), index=False)

    print(
        f"Done. assets={len(registry)} tickets={len(tickets)} "
        f"telemetry={len(telemetry)} claims={len(claims)}"
    )
    print(f"Output dir: {OUT_DIR}")


if __name__ == "__main__":
    main()
