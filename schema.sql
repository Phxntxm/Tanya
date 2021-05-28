CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    alignment INT NOT NULL,
    defence_level INT,
    attack_level INT,
    description TEXT,
    blurb TEXT,
    save_message TEXT,
    attack_message TEXT,
    suicide_message TEXT
);
CREATE TABLE IF NOT EXISTS games (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    config TEXT NOT NULL,
    day_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS players (
    game_id INT NOT NULL REFERENCES games (id),
    user_id BIGINT NOT NULL,
    PRIMARY KEY (game_id, user_id),
    role INTEGER NOT NULL REFERENCES roles (id),
    win BOOLEAN,
    die BOOLEAN NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS kills (
    game_id INT NOT NULL REFERENCES games (id),
    killer BIGINT,
    killed BIGINT NOT NULL,
    night INT NOT NULL,
    suicide BOOLEAN NOT NULL
);