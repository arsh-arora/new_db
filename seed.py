#!/usr/bin/env python3
import os, json, random, math, hashlib
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import execute_values
from faker import Faker

DB_URL = os.getenv("DATABASE_URL", "postgresql://accurate:accurate@localhost:5432/accurate")
RNG_SEED = int(os.getenv("SEED", "7"))
DAYS = int(os.getenv("DAYS", "180"))
N_COMPANIES = int(os.getenv("N_COMPANIES", "12"))
SUBJECTS_PER_COMPANY = int(os.getenv("SUBJECTS_PER_COMPANY", "400"))
PKG_PER_COMPANY_MIN = 2
PKG_PER_COMPANY_MAX = 6
ORDERS_PER_COMPANY_MEAN_PER_DAY = float(os.getenv("ORDERS_MEAN", "2.5"))

COMPONENT_CATALOG = ["CRIM","EDU","EMP","ADDRESS","IDCHECK","MVR","REF","DRUGTEST"]
NOW = datetime.now(timezone.utc)

rng = random.Random(RNG_SEED)
fake = Faker()
Faker.seed(RNG_SEED)

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def pick_components():
    k = rng.randint(2, 6)
    return sorted(rng.sample(COMPONENT_CATALOG, k))

def status_mix():
    # target: COMPLETED 60–75, IN_PROGRESS 10–20, PENDING 5–10, CANCELLED 5–8, REOPENED 1–3, DRAFT tiny
    x = rng.random()
    if x < 0.02: return "DRAFT"
    if x < 0.10: return "PENDING"
    if x < 0.28: return "IN_PROGRESS"
    if x < 0.35: return "CANCELLED"
    if x < 0.38: return "REOPENED"
    return "COMPLETED"

def tat_bucket(h):
    if h is None: return None
    if h <= 24: return "<=24h"
    if h <= 48: return "24–48h"
    if h <= 72: return "48–72h"
    return ">72h"

def generate():
    companies = []
    subjects = []
    packages = []
    orders = []
    components = []

    # 1) companies
    for i in range(N_COMPANIES):
        code = f"C{i+1:03d}"
        companies.append((
            code,
            f"{fake.company()} Ltd",
            f"{fake.city()}, {fake.state()}",
            rng.choice(["Healthcare","IT","Manufacturing","Retail","Finance","Logistics"]),
            True,
            None if rng.random() > 0.2 else f"C{rng.randint(1,max(1,i)):03d}",
            f"BA-{rng.randint(100000,999999)}",
            rng.choice([24,36,48,72]),
            rng.choice([365,730,1095]),
            NOW, NOW
        ))

    # 2) subjects
    subj_id = 0
    for comp in companies:
        comp_code = comp[0]
        for _ in range(SUBJECTS_PER_COMPANY):
            subj_id += 1
            dob = fake.date_of_birth(minimum_age=20, maximum_age=55)
            email = f"{fake.user_name()}@{fake.free_email_domain()}"
            phone = fake.msisdn()
            city, state, country = fake.city(), fake.state(), "IN"
            has_consent = rng.random() > 0.05
            subjects.append((
                subj_id, comp_code, fake.name(), dob,
                email, phone, city, state, country,
                sha256(f"{email}:{dob}"),
                rng.choice(["LOW","MED","HIGH"]),
                NOW - timedelta(days=rng.randint(1, 365)) if has_consent else None,
                f"v{rng.choice([1,1,1,2])}" if has_consent else None,
                f"cand-{subj_id:08d}",
                NOW, NOW
            ))

    # 3) packages
    for comp in companies:
        comp_code = comp[0]
        k = rng.randint(PKG_PER_COMPANY_MIN, PKG_PER_COMPANY_MAX)
        for p in range(k):
            pkg_code = f"{comp_code}-PKG-{p+1}"
            pkg_name = rng.choice(["PreHire","Standard","Enhanced","Managerial","Periodic","Custom"]) + f" {p+1}"
            price = round(rng.uniform(500, 5000), 2)
            category = rng.choice(["PREHIRE","PERIODIC","CUSTOM"])
            version = rng.choice([1,1,1,2])
            comps = pick_components()
            packages.append((
                pkg_code, comp_code, pkg_name, price, category, version,
                json.dumps(comps), f"BC-{rng.randint(1000,9999)}", True, NOW, NOW
            ))

    # Helper maps
    comp_codes = [c[0] for c in companies]
    comp_to_pkg = {}
    for pkg in packages:
        comp_to_pkg.setdefault(pkg[1], []).append(pkg)

    comp_to_subjects = {}
    for s in subjects:
        comp_to_subjects.setdefault(s[1], []).append(s)

    # 4) orders
    order_id = 0
    for comp_code in comp_codes:
        pkgs = comp_to_pkg[comp_code]
        subs = comp_to_subjects[comp_code]
        for d in range(DAYS):
            day = NOW - timedelta(days=(DAYS - d))
            # weekday bias
            mu = ORDERS_PER_COMPANY_MEAN_PER_DAY * (1.2 if day.weekday() < 5 else 0.6)
            n = rng.poisson(mu) if hasattr(rng, "poisson") else max(0, int(rng.gauss(mu, max(0.3, mu*0.25))))
            for _ in range(n):
                order_id += 1
                pkg = rng.choice(pkgs)
                sub = rng.choice(subs)
                status = status_mix()
                created_at = day + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0,59))
                submitted_at = created_at + timedelta(hours=rng.randint(0, 8)) if status != "DRAFT" else None
                completed_at = None
                cancelled_at = None
                sla_target = rng.choice([24,36,48,72])
                tat_h = None
                if status == "COMPLETED":
                    dur = rng.randint(6, int(sla_target*1.8))
                    completed_at = (submitted_at or created_at) + timedelta(hours=dur)
                    tat_h = math.ceil((completed_at - (submitted_at or created_at)).total_seconds()/3600)
                elif status == "CANCELLED":
                    cancelled_at = (submitted_at or created_at) + timedelta(hours=rng.randint(1, 12))
                elif status == "REOPENED":
                    # treat as in-progress with reopen history
                    pass

                mr = rng.random() < 0.015
                dmr = rng.random() < 0.04
                adj = "REVIEW" if (mr or dmr) and status in ("COMPLETED","REOPENED") else None

                list_price = pkg[3]
                disc = rng.choice([0,0,5,10,15])
                net = round(list_price * (1 - disc/100.0), 2) if status != "CANCELLED" else None
                email = f"{fake.user_name()}@{fake.free_email_domain()}" if rng.random()>0.2 else None
                chan = rng.choice(["PORTAL","API","BULK"])

                orders.append((
                    order_id, comp_code, sub[0], pkg[0], status,
                    created_at, submitted_at, completed_at, cancelled_at, rng.choice([0,0,0,1]),
                    sla_target, tat_h, tat_bucket(tat_h),
                    dmr, mr, adj,
                    email, chan,
                    list_price, disc, net, None,
                    None  # search_text
                ))

                # 5) components per order (from package.components_json)
                comps = json.loads(pkg[6])
                for ct in comps:
                    c_status = status
                    start_ts = (submitted_at or created_at) + timedelta(hours=rng.randint(0, 6))
                    end_ts = None
                    tat_c = None
                    aging = None
                    if c_status == "COMPLETED":
                        dur = rng.randint(2, int(24*1.8))
                        end_ts = start_ts + timedelta(hours=dur)
                        tat_c = dur
                    elif c_status in ("PENDING","IN_PROGRESS","REOPENED"):
                        # aging from last update
                        aging = rng.randint(1, 72)
                    elif c_status == "CANCELLED":
                        end_ts = (submitted_at or created_at) + timedelta(hours=rng.randint(1, 12))

                    result_flag = rng.choice(["FOUND","NOT_FOUND","NA"]) if c_status != "PENDING" else None
                    jurisdiction = None
                    if ct in ("CRIM","MVR","ADDRESS"):
                        jurisdiction = rng.choice(["IN-DL","IN-MH","IN-KA","IN-TN","IN-GJ","IN-UP"])

                    evidence_uri = None
                    prov = None
                    if result_flag == "FOUND":
                        evidence_uri = f"s3://evidence/{order_id}/{ct.lower()}_{rng.randint(1000,9999)}.pdf"
                        prov = sha256(f"{order_id}:{ct}:{evidence_uri}")

                    components.append((
                        order_id, ct, c_status, result_flag,
                        start_ts, end_ts,
                        f"V-{rng.randint(100,999)}" if rng.random()>0.5 else None,
                        jurisdiction,
                        rng.choice(["EXTSYS","MANUAL","API"]) if rng.random()>0.4 else None,
                        rng.randint(1,3), None, rng.choice([0,0,1]),
                        24, tat_c, aging,
                        evidence_uri, prov,
                        start_ts + timedelta(hours=rng.randint(1,6)) if c_status in ("PENDING","IN_PROGRESS","REOPENED") else (end_ts or start_ts),
                        start_ts
                    ))

    return companies, subjects, packages, orders, components

def main():
    print("Generating data...")
    companies, subjects, packages, orders, components = generate()

    print("Connecting to DB...")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    # Truncate in case you rerun
    for t in ["search","order_request","package","subject","company"]:
        cur.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE;")

    print("Inserting companies...")
    execute_values(cur,
        """INSERT INTO company(
            comp_code, company_name, location, industry, active, parent_comp_code,
            billing_account_id, default_sla_hours, data_retention_days, created_at, updated_at
          ) VALUES %s""",
        companies, page_size=1000)

    print("Inserting subjects...")
    execute_values(cur,
        """INSERT INTO subject(
           subject_id, comp_code, subject_name, subject_dob, subject_email, subject_phone,
           subject_city, subject_state, subject_country, gov_id_hash, pii_class,
           consent_received_at, consent_version, candidate_portal_id, created_at, updated_at
        ) VALUES %s""",
        subjects, page_size=2000)

    print("Inserting packages...")
    execute_values(cur,
        """INSERT INTO package(
           package_code, comp_code, package_name, package_price, package_category,
           package_version, components_json, billing_code, is_active, created_at, updated_at
        ) VALUES %s""",
        packages, page_size=1000)

    print("Inserting orders...")
    execute_values(cur,
        """INSERT INTO order_request(
           order_id, comp_code, subject_id, package_code, status,
           created_at, submitted_at, completed_at, cancelled_at, reopened_count,
           sla_target_hours, tat_hours, tat_bucket,
           dmr_flag, mr_flag, adjudication_result,
           created_by_email, channel,
           list_price, discount_pct, net_amount, invoice_ref,
           search_text
        ) VALUES %s""",
        orders, page_size=2000)

    print("Inserting search components...")
    execute_values(cur,
        """INSERT INTO search(
           order_id, component_type, status, result_flag,
           start_date, end_date,
           vendor_ref, jurisdiction, source_system,
           attempts, last_error_code, escalation_level,
           sla_target_hours, tat_hours, aging_hours,
           evidence_uri, provenance_hash,
           last_updated_at, created_at
        ) VALUES %s""",
        components, page_size=5000)

    print("Post-load coherence fixes...")
    # Derive net_amount if missing
    cur.execute("""
      UPDATE order_request
      SET net_amount = COALESCE(list_price,0) * (1 - COALESCE(discount_pct,0)/100.0)
      WHERE net_amount IS NULL AND list_price IS NOT NULL;
    """)
    # Recompute tat_bucket (safety)
    cur.execute("""
      UPDATE order_request
      SET tat_bucket = CASE
        WHEN tat_hours IS NULL THEN NULL
        WHEN tat_hours <= 24 THEN '<=24h'
        WHEN tat_hours <= 48 THEN '24–48h'
        WHEN tat_hours <= 72 THEN '48–72h'
        ELSE '>72h' END;
    """)
    # Aging for active components
    cur.execute("""
      UPDATE search
      SET aging_hours = GREATEST(0, CEIL(EXTRACT(EPOCH FROM (now() - last_updated_at))/3600.0))
      WHERE status IN ('PENDING','IN_PROGRESS','REOPENED','WAITING_VENDOR')
        AND last_updated_at IS NOT NULL;
    """)

    cur.close()
    conn.close()
    print("Seeding complete.")

if __name__ == "__main__":
    main()
