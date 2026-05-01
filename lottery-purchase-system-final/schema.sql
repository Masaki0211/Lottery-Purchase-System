DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS ticket_types;
DROP TABLE IF EXISTS prize_rules;
DROP TABLE IF EXISTS game_rules;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'customer',
    dob TEXT
);

CREATE TABLE ticket_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_name TEXT NOT NULL,
    price REAL NOT NULL,
    drawing_date TEXT NOT NULL,
    prize_amount REAL NOT NULL,
    winning_numbers TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    ticket_type_id INTEGER NOT NULL,
    selected_numbers TEXT NOT NULL,
    selection_mode TEXT NOT NULL,
    confirmation_number TEXT NOT NULL UNIQUE,
    is_winner INTEGER NOT NULL DEFAULT 0,
    match_count INTEGER NOT NULL DEFAULT 0,
    winning_amount REAL NOT NULL DEFAULT 0,
    result_status TEXT NOT NULL DEFAULT 'pending_drawing',
    claim_status TEXT NOT NULL DEFAULT 'not_claimed',
    claim_method TEXT,
    claim_date TEXT,
    claim_code TEXT,
    payout_type TEXT DEFAULT 'none',
    tax_withheld REAL DEFAULT 0,
    net_payout REAL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (ticket_type_id) REFERENCES ticket_types (id)
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    payment_method TEXT NOT NULL,
    amount REAL NOT NULL,
    payment_status TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders (id)
);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_by TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    total_revenue REAL NOT NULL,
    report_data TEXT NOT NULL
);