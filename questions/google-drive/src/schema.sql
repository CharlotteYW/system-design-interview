CREATE TABLE IF NOT EXISTS files (
 id text PRIMARY KEY, owner text NOT NULL, name text NOT NULL, mime text NOT NULL,
 revision bigint NOT NULL DEFAULT 0, manifest_id text, size bigint NOT NULL DEFAULT 0,
 deleted_at double precision, created_at double precision NOT NULL, updated_at double precision NOT NULL
);
CREATE INDEX IF NOT EXISTS files_owner ON files(owner, id);
CREATE TABLE IF NOT EXISTS uploads (
 id text PRIMARY KEY, owner text NOT NULL, file_id text NOT NULL REFERENCES files(id),
 idem_key text NOT NULL, request jsonb NOT NULL, state text NOT NULL DEFAULT 'uploading',
 plan_hash text, policy jsonb, result jsonb, conflict_revision bigint,
 resolution_key text, resolution_request jsonb, reconcile_requested boolean NOT NULL DEFAULT false,
 created_at double precision NOT NULL, expires_at double precision NOT NULL,
 UNIQUE(owner, idem_key)
);
CREATE TABLE IF NOT EXISTS chunk_objects (
 id text PRIMARY KEY, owner text NOT NULL, object_key text UNIQUE NOT NULL,
 version text, meta jsonb NOT NULL, state text NOT NULL DEFAULT 'staged',
 created_at double precision NOT NULL, protect_until double precision NOT NULL DEFAULT 0,
 unreferenced_since double precision, delete_token text, deleted_at double precision
);
CREATE INDEX IF NOT EXISTS chunk_gc ON chunk_objects(state, unreferenced_since);
CREATE TABLE IF NOT EXISTS upload_chunks (
 upload_id text REFERENCES uploads(id), ordinal integer NOT NULL, chunk_id text NOT NULL REFERENCES chunk_objects(id),
 expected jsonb NOT NULL, state text NOT NULL DEFAULT 'planned', receipt jsonb, last_error text,
 PRIMARY KEY(upload_id, ordinal)
);
CREATE TABLE IF NOT EXISTS manifests (
 id text PRIMARY KEY, file_id text NOT NULL REFERENCES files(id), owner text NOT NULL,
 policy jsonb NOT NULL, size bigint NOT NULL, created_at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS manifest_chunks (
 manifest_id text REFERENCES manifests(id), ordinal integer NOT NULL,
 chunk_id text NOT NULL REFERENCES chunk_objects(id), PRIMARY KEY(manifest_id, ordinal)
);
CREATE INDEX IF NOT EXISTS manifest_chunk_lookup ON manifest_chunks(chunk_id);
CREATE TABLE IF NOT EXISTS access (
 user_id text NOT NULL, file_id text NOT NULL REFERENCES files(id), role text NOT NULL DEFAULT 'reader',
 PRIMARY KEY(user_id, file_id)
);
CREATE INDEX IF NOT EXISTS access_reverse ON access(file_id, user_id);
CREATE TABLE IF NOT EXISTS user_streams (user_id text PRIMARY KEY, last_seq bigint NOT NULL DEFAULT 0, floor_seq bigint NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS changes (
 user_id text NOT NULL, seq bigint NOT NULL, source_event_id text NOT NULL,
 file_id text NOT NULL, revision bigint NOT NULL, type text NOT NULL, created_at double precision NOT NULL,
 PRIMARY KEY(user_id, seq), UNIQUE(user_id, source_event_id)
);
CREATE TABLE IF NOT EXISTS outbox (
 id text PRIMARY KEY, source_upload_id text UNIQUE, owner text NOT NULL, file_id text NOT NULL,
 revision bigint NOT NULL, type text NOT NULL, cursor text NOT NULL DEFAULT '',
 processed integer NOT NULL DEFAULT 0, state text NOT NULL DEFAULT 'pending',
 lease_owner text, lease_until double precision NOT NULL DEFAULT 0, lease_epoch bigint NOT NULL DEFAULT 0,
 created_at double precision NOT NULL
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(state, created_at);
CREATE TABLE IF NOT EXISTS download_sessions (
 id text PRIMARY KEY, user_id text NOT NULL, file_id text NOT NULL REFERENCES files(id),
 manifest_id text NOT NULL REFERENCES manifests(id), revision bigint NOT NULL,
 expires_at double precision NOT NULL, protect_until double precision NOT NULL,
 state text NOT NULL DEFAULT 'active', created_at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS replica_model (
 upload_id text PRIMARY KEY, result jsonb NOT NULL
);
