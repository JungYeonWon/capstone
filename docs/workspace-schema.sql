-- Apply before deploying document workflow improvements. No application DDL privileges required.
CREATE TABLE IF NOT EXISTS capstone.workspace_states (
    contract_id INTEGER NOT NULL REFERENCES capstone.contracts(id) ON DELETE CASCADE,
    slot VARCHAR(40) NOT NULL,
    payload JSON NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (contract_id, slot)
);
CREATE INDEX IF NOT EXISTS ix_capstone_workspace_states_updated_at ON capstone.workspace_states(updated_at);
ALTER TABLE capstone.workspace_states ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON capstone.workspace_states;
CREATE POLICY backend_access ON capstone.workspace_states FOR ALL TO capstone_api USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON capstone.workspace_states TO capstone_api;
