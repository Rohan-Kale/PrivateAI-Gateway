CREATE TABLE IF NOT EXISTS policies (
    tenant TEXT PRIMARY KEY CHECK (tenant ~ '^[a-zA-Z0-9_-]{1,64}$'),
    version BIGINT NOT NULL CHECK (version > 0),
    document JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO policies(tenant, version, document) VALUES
('demo', 1, '{"default":"redact","rules":{"SECRET":"block","EMAIL":"tokenize"},"restore":true,"cache_seconds":60}')
ON CONFLICT DO NOTHING;
