CREATE TABLE IF NOT EXISTS business_cell_keys (
    method text NOT NULL CHECK (method IN ('s2', 'h3')),
    cell_id text COLLATE "C" NOT NULL,
    business_id uuid NOT NULL REFERENCES businesses (business_id) ON DELETE CASCADE,
    PRIMARY KEY (method, cell_id, business_id),
    UNIQUE (business_id, method)
);

GRANT SELECT ON business_cell_keys TO proximity_search;
