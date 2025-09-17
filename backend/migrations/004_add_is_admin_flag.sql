-- Adds an explicit admin flag to student records.
ALTER TABLE students
    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT 0;

-- Promote the default admin account.
UPDATE students
SET is_admin = 1
WHERE slug = 'dalarcon80';
