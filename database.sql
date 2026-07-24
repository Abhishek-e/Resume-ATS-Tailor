-- On Render, the database itself is already created for you when you
-- link a Postgres instance in render.yaml. This script only needs to
-- create the table structure. Run it once against your database
-- (e.g. via the psql shell Render gives you, or locally for dev).

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL
);
