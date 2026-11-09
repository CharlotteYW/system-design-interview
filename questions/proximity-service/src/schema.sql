CREATE EXTENSION postgis;

CREATE TABLE businesses (
    business_id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    name text NOT NULL,
    category text NOT NULL,
    address text NOT NULL,
    location geography(Point, 4326) NOT NULL,
    geohash text GENERATED ALWAYS AS (ST_GeoHash(location::geometry, 4)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX businesses_location_idx ON businesses USING gist (location);
CREATE INDEX businesses_geohash_idx ON businesses (geohash);

CREATE TABLE creation_requests (
    owner_id text NOT NULL,
    idempotency_key uuid NOT NULL,
    request_fingerprint bytea NOT NULL,
    business_id uuid REFERENCES businesses (business_id),
    response_status smallint,
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, idempotency_key)
);

CREATE ROLE proximity_search LOGIN PASSWORD 'search';
GRANT CONNECT ON DATABASE proximity TO proximity_search;
GRANT USAGE ON SCHEMA public TO proximity_search;
GRANT SELECT ON businesses TO proximity_search;
