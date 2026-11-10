CREATE EXTENSION postgis;
CREATE EXTENSION pg_trgm;

CREATE TABLE users (
    user_id text PRIMARY KEY,
    display_name text NOT NULL
);

CREATE TABLE businesses (
    business_id text PRIMARY KEY,
    name text NOT NULL,
    category text NOT NULL,
    address text NOT NULL,
    location geometry(Point, 4326) NOT NULL
);
CREATE INDEX businesses_boundary_idx ON businesses USING gist (location);
CREATE INDEX businesses_radius_idx ON businesses USING gist ((location::geography));
CREATE INDEX businesses_category_idx ON businesses (category);
CREATE INDEX businesses_name_trgm ON businesses USING gin (name gin_trgm_ops);
CREATE INDEX businesses_name_words ON businesses USING gin (to_tsvector('simple', name));

CREATE TABLE places (
    place_id text PRIMARY KEY,
    name text NOT NULL,
    region text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('city', 'neighborhood')),
    center geometry(Point, 4326) NOT NULL,
    boundary geometry(MultiPolygon, 4326) NOT NULL CHECK (ST_IsValid(boundary))
);
CREATE INDEX places_name_idx ON places (lower(name) text_pattern_ops);

-- Materialized membership variant. The seed has no catalog update API.
CREATE TABLE business_places (
    place_id text NOT NULL REFERENCES places,
    business_id text NOT NULL REFERENCES businesses,
    PRIMARY KEY (place_id, business_id)
);

CREATE TABLE reviews (
    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL REFERENCES users,
    business_id text NOT NULL REFERENCES businesses,
    rating smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    direct_retry_key text,
    UNIQUE (user_id, business_id),
    UNIQUE (user_id, direct_retry_key)
);
CREATE INDEX reviews_by_business ON reviews (business_id, created_at DESC, review_id DESC);
CREATE INDEX reviews_by_author ON reviews (user_id, created_at DESC, review_id DESC);

CREATE TABLE business_rating_stats (
    business_id text PRIMARY KEY REFERENCES businesses,
    rating_sum bigint NOT NULL,
    review_count bigint NOT NULL CHECK (review_count > 0)
);

CREATE TABLE review_submissions (
    submission_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL REFERENCES users,
    business_id text NOT NULL REFERENCES businesses,
    idempotency_key text NOT NULL,
    rating smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'saved', 'failed')),
    review_id uuid REFERENCES reviews,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    attempt_count integer NOT NULL DEFAULT 0,
    batch_rating boolean NOT NULL DEFAULT false,
    UNIQUE (user_id, idempotency_key),
    CHECK ((status = 'saved') = (review_id IS NOT NULL)),
    CHECK ((status = 'failed') = (error_code IS NOT NULL))
);
CREATE INDEX pending_reviews ON review_submissions (created_at, submission_id) WHERE status = 'pending';

CREATE TABLE rating_outbox (
    review_id uuid PRIMARY KEY REFERENCES reviews,
    business_id text NOT NULL REFERENCES businesses,
    rating smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    applied_at timestamptz
);
CREATE INDEX pending_ratings ON rating_outbox (created_at, review_id) WHERE applied_at IS NULL;

INSERT INTO users VALUES ('lee', 'Lee'), ('kim', 'Kim'), ('ada', 'Ada');

-- Simplified polygons for the fixture. These are not official boundaries.
INSERT INTO places (place_id, name, region, kind, center, boundary)
VALUES
    ('sf-ca', 'San Francisco', 'California', 'city', ST_SetSRID(ST_MakePoint(-122.423, 37.762), 4326),
     ST_GeomFromText('MULTIPOLYGON(((-122.515 37.707,-122.36 37.707,-122.36 37.76,-122.405 37.81,-122.50 37.81,-122.515 37.707)))',4326)),
    ('sf-mission', 'Mission District', 'San Francisco, California', 'neighborhood', ST_SetSRID(ST_MakePoint(-122.419, 37.759), 4326),
     ST_GeomFromText('MULTIPOLYGON(((-122.433 37.744,-122.401 37.744,-122.401 37.768,-122.414 37.773,-122.433 37.764,-122.433 37.744)))',4326));

INSERT INTO businesses
SELECT id, name, category, address, ST_SetSRID(ST_MakePoint(lon, lat),4326)
FROM (VALUES
    ('sunny-ramen','Sunny Ramen','restaurant','Mission District',-122.419,37.758),
    ('mission-pizza','Mission Pizza','restaurant','Mission District',-122.414,37.755),
    ('north-ramen','North Ramen','restaurant','North Beach',-122.409,37.800),
    ('ramen-books','Ramen Books','bookstore','Mission District',-122.423,37.756),
    ('outside-ramen','East Bay Ramen','restaurant','Oakland',-122.274,37.804),
    ('ramenhouse','Ramenhouse','restaurant','SoMa',-122.399,37.782),
    ('sunset-ramen','Sunset Ramen','restaurant','Outer Sunset',-122.501,37.752)
) AS seed(id,name,category,address,lon,lat);

INSERT INTO business_places
SELECT p.place_id, b.business_id FROM places p JOIN businesses b ON ST_Covers(p.boundary,b.location);

INSERT INTO reviews (user_id, business_id, rating, text)
VALUES ('ada','sunny-ramen',4,'Rich broth.'), ('kim','mission-pizza',5,'Great crust.');
INSERT INTO business_rating_stats
SELECT business_id, sum(rating), count(*) FROM reviews GROUP BY business_id;
