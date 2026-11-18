-- Apply before deploying review history. Existing contracts and documents are preserved.
CREATE TABLE IF NOT EXISTS capstone.clause_reviews (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES capstone.contracts(id) ON DELETE CASCADE,
    payload JSON NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_capstone_clause_reviews_contract_id ON capstone.clause_reviews(contract_id);
ALTER TABLE capstone.clause_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON capstone.clause_reviews;
CREATE POLICY backend_access ON capstone.clause_reviews FOR ALL TO capstone_api USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON capstone.clause_reviews TO capstone_api;
GRANT USAGE, SELECT ON SEQUENCE capstone.clause_reviews_id_seq TO capstone_api;
