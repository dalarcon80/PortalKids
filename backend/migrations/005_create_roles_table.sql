-- Creates a persistent catalog of roles for students and missions.
CREATE TABLE IF NOT EXISTS roles (
    slug TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- Seed common roles required by the application.
INSERT INTO roles (slug, name, metadata_json)
SELECT 'admin', 'admin', '{"is_admin": true, "aliases": ["administrador", "administradora", "administrator", "admin"]}'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE slug = 'admin');

INSERT INTO roles (slug, name, metadata_json)
SELECT 'learner', 'learner', '{}'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE slug = 'learner');

INSERT INTO roles (slug, name, metadata_json)
SELECT 'explorer', 'explorer', '{}'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE slug = 'explorer');

INSERT INTO roles (slug, name, metadata_json)
SELECT 'ventas', 'Ventas', '{}'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE slug = 'ventas');

INSERT INTO roles (slug, name, metadata_json)
SELECT 'operaciones', 'Operaciones', '{}'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE slug = 'operaciones');
