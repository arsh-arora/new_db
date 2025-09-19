-- 1) company
CREATE TABLE IF NOT EXISTS company (
  comp_code           TEXT PRIMARY KEY,
  company_name        TEXT NOT NULL,
  location            TEXT,
  industry            TEXT,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  parent_comp_code    TEXT NULL REFERENCES company(comp_code),
  billing_account_id  TEXT NULL,
  default_sla_hours   INT  NOT NULL DEFAULT 48,
  data_retention_days INT  NOT NULL DEFAULT 365,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT company_name_uniq UNIQUE (company_name)
);
CREATE INDEX IF NOT EXISTS idx_company_active ON company(active);

-- 2) subject
CREATE TABLE IF NOT EXISTS subject (
  subject_id          BIGSERIAL PRIMARY KEY,
  comp_code           TEXT NOT NULL REFERENCES company(comp_code),
  subject_name        TEXT NOT NULL,
  subject_dob         DATE,
  subject_email       TEXT,
  subject_phone       TEXT,
  subject_city        TEXT,
  subject_state       TEXT,
  subject_country     TEXT,
  gov_id_hash         TEXT,
  pii_class           TEXT NOT NULL DEFAULT 'MED',  -- LOW/MED/HIGH
  consent_received_at TIMESTAMPTZ,
  consent_version     TEXT,
  candidate_portal_id TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT email_format_chk CHECK (subject_email IS NULL OR subject_email LIKE '%@%')
);
CREATE INDEX IF NOT EXISTS idx_subject_comp ON subject(comp_code);
CREATE INDEX IF NOT EXISTS idx_subject_email_comp ON subject(comp_code, subject_email);

-- 3) package
CREATE TABLE IF NOT EXISTS package (
  package_code     TEXT PRIMARY KEY,
  comp_code        TEXT NOT NULL REFERENCES company(comp_code),
  package_name     TEXT NOT NULL,
  package_price    NUMERIC(12,2) NOT NULL CHECK (package_price >= 0),
  package_category TEXT NOT NULL DEFAULT 'PREHIRE',  -- PREHIRE/PERIODIC/CUSTOM
  package_version  INT  NOT NULL DEFAULT 1,
  components_json  JSONB NOT NULL DEFAULT '[]',      -- ["CRIM","EDU",...]
  billing_code     TEXT,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT package_name_ver_uniq UNIQUE (comp_code, package_name, package_version)
);
CREATE INDEX IF NOT EXISTS idx_package_comp ON package(comp_code);
CREATE INDEX IF NOT EXISTS idx_package_components_gin ON package USING GIN (components_json);

-- 4) order_request
CREATE TABLE IF NOT EXISTS order_request (
  order_id          BIGSERIAL PRIMARY KEY,
  comp_code         TEXT NOT NULL REFERENCES company(comp_code),
  subject_id        BIGINT NOT NULL REFERENCES subject(subject_id),
  package_code      TEXT NOT NULL REFERENCES package(package_code),
  status            TEXT NOT NULL DEFAULT 'PENDING',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  submitted_at      TIMESTAMPTZ,
  completed_at      TIMESTAMPTZ,
  cancelled_at      TIMESTAMPTZ,
  reopened_count    INT NOT NULL DEFAULT 0,

  sla_target_hours  INT NOT NULL DEFAULT 48,
  tat_hours         INT,
  tat_bucket        TEXT,

  dmr_flag          BOOLEAN NOT NULL DEFAULT FALSE,
  mr_flag           BOOLEAN NOT NULL DEFAULT FALSE,
  adjudication_result TEXT,     -- MR/DMR/CLEAR/REVIEW

  created_by_email  TEXT,
  channel           TEXT NOT NULL DEFAULT 'PORTAL',   -- PORTAL/API/BULK

  list_price        NUMERIC(12,2),
  discount_pct      NUMERIC(5,2),
  net_amount        NUMERIC(12,2),
  invoice_ref       TEXT,

  search_text       TSVECTOR,

  CONSTRAINT status_chk CHECK (status IN
    ('DRAFT','PENDING','IN_PROGRESS','COMPLETED','CANCELLED','REOPENED')),
  CONSTRAINT tat_nonneg_chk CHECK (tat_hours IS NULL OR tat_hours >= 0),
  CONSTRAINT discount_range_chk CHECK (discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100))
);
CREATE INDEX IF NOT EXISTS idx_order_comp_created ON order_request(comp_code, created_at);
CREATE INDEX IF NOT EXISTS idx_order_status ON order_request(status);
CREATE INDEX IF NOT EXISTS idx_order_package ON order_request(package_code);
CREATE INDEX IF NOT EXISTS idx_order_searchtext ON order_request USING GIN (search_text);

-- 5) search (component instances)
CREATE TABLE IF NOT EXISTS search (
  component_id     BIGSERIAL PRIMARY KEY,
  order_id         BIGINT NOT NULL REFERENCES order_request(order_id) ON DELETE CASCADE,
  component_type   TEXT NOT NULL,                         -- CRIM/EDU/EMP/MVR/DHS/REF/ADDRESS/IDCHECK/DRUGTEST
  status           TEXT NOT NULL DEFAULT 'PENDING',
  result_flag      TEXT,                                  -- FOUND/NOT_FOUND/NA

  start_date       TIMESTAMPTZ NOT NULL DEFAULT now(),
  end_date         TIMESTAMPTZ,

  vendor_ref       TEXT,
  jurisdiction     TEXT,
  source_system    TEXT,

  attempts         INT NOT NULL DEFAULT 0,
  last_error_code  TEXT,
  escalation_level INT NOT NULL DEFAULT 0,

  sla_target_hours INT NOT NULL DEFAULT 24,
  tat_hours        INT,
  aging_hours      INT,

  evidence_uri     TEXT,
  provenance_hash  TEXT,

  last_updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT component_type_chk CHECK (component_type ~ '^[A-Z_]+$'),
  CONSTRAINT search_tat_nonneg_chk CHECK (tat_hours IS NULL OR tat_hours >= 0),
  CONSTRAINT aging_nonneg_chk CHECK (aging_hours IS NULL OR aging_hours >= 0)
);
CREATE INDEX IF NOT EXISTS idx_search_order ON search(order_id);
CREATE INDEX IF NOT EXISTS idx_search_type_status ON search(component_type, status);
CREATE INDEX IF NOT EXISTS idx_search_created ON search(created_at);

-- 6) search_status (state reference + transition semantics)
CREATE TABLE IF NOT EXISTS search_status (
  status_code       TEXT PRIMARY KEY,        -- PENDING, IN_PROGRESS, WAITING_VENDOR, COMPLETE, CANCELLED, REOPENED
  status_label      TEXT NOT NULL,
  from_status       TEXT,
  to_status         TEXT,
  transition_allowed BOOLEAN NOT NULL DEFAULT TRUE,
  is_terminal       BOOLEAN NOT NULL DEFAULT FALSE,
  semantic          TEXT,                    -- ACTIVE/WAITING/DONE
  sla_scalar        NUMERIC(4,2) NOT NULL DEFAULT 1.00,
  bucket            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_search_transition ON search_status(from_status, to_status);

-- Views (stable BI/agent surfaces)
CREATE OR REPLACE VIEW v_order_fact AS
SELECT
  o.order_id, o.comp_code, o.package_code, o.subject_id, o.status,
  o.created_at, o.submitted_at, o.completed_at, o.tat_hours, o.tat_bucket,
  o.dmr_flag, o.mr_flag, o.adjudication_result, o.net_amount
FROM order_request o;

CREATE OR REPLACE VIEW v_search_fact AS
SELECT
  s.component_id, s.order_id, s.component_type, s.status,
  s.created_at, s.last_updated_at, s.tat_hours, s.aging_hours,
  s.vendor_ref, s.jurisdiction, s.attempts, s.escalation_level, s.result_flag
FROM search s;
