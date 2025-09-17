-- Creates persistent storage for login sessions.
CREATE TABLE IF NOT EXISTS sessions (
    token VARCHAR(255) NOT NULL,
    student_slug VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (token),
    KEY idx_sessions_student_slug (student_slug),
    CONSTRAINT fk_sessions_student_slug
        FOREIGN KEY (student_slug)
        REFERENCES students (slug)
        ON DELETE CASCADE
);
