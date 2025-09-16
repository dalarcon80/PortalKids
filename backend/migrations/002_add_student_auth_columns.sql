-- Adds email and password hash support for student authentication.
ALTER TABLE students
    ADD COLUMN IF NOT EXISTS email TEXT;

ALTER TABLE students
    ADD COLUMN IF NOT EXISTS password_hash TEXT;
