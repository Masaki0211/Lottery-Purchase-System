import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import random
import string

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-to-something-random"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with open("schema.sql", mode="r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()


# ---------------------------------------------------------------------------
# Default 4 games — seeded on startup if DB is empty
# To disable auto-seed, comment out the call in ensure_default_games()
# ---------------------------------------------------------------------------
DEFAULT_GAMES = [
    {
        "game_name": "Power Ball",
        "main_count": 5,
        "main_range": 69,
        "bonus_range": 26,
        "price": 2.00,
        "prize_amount": 1000000.00,
        "prize_rules": [
            (5, True, 1000000.00),
            (5, False, 500000.00),
            (4, True, 50000.00),
            (4, False, 100.00),
            (3, True, 100.00),
            (3, False, 7.00),
            (2, True, 7.00),
            (1, True, 4.00),
            (0, True, 4.00),
        ],
    },
    {
        "game_name": "Mega Millions",
        "main_count": 5,
        "main_range": 70,
        "bonus_range": 25,
        "price": 2.00,
        "prize_amount": 2000000.00,
        "prize_rules": [
            (5, True, 2000000.00),
            (5, False, 1000000.00),
            (4, True, 10000.00),
            (4, False, 500.00),
            (3, True, 200.00),
            (3, False, 10.00),
            (2, True, 10.00),
            (1, True, 4.00),
            (0, True, 2.00),
        ],
    },
    {
        "game_name": "Lotto Texas",
        "main_count": 6,
        "main_range": 54,
        "bonus_range": None,
        "price": 1.00,
        "prize_amount": 500000.00,
        "prize_rules": [
            (6, False, 500000.00),
            (5, False, 5000.00),
            (4, False, 50.00),
            (3, False, 3.00),
        ],
    },
    {
        "game_name": "Texas Two Step",
        "main_count": 4,
        "main_range": 35,
        "bonus_range": 35,
        "price": 1.50,
        "prize_amount": 250000.00,
        "prize_rules": [
            (4, True, 250000.00),
            (4, False, 1000.00),
            (3, True, 25.00),
            (3, False, 5.00),
            (2, True, 5.00),
            (1, True, 2.50),
            (0, True, 2.50),
        ],
    },
]


def ensure_default_games():
    """Seed default 4 games on startup if DB is empty. Comment out body to disable."""
    db = get_db()
    for g_def in DEFAULT_GAMES:
        name = g_def["game_name"]

        # game_rules
        existing = db.execute("SELECT id FROM game_rules WHERE game_name=?", (name,)).fetchone()
        if not existing:
            db.execute("""
                INSERT INTO game_rules (game_name, main_count, main_range, bonus_range)
                VALUES (?, ?, ?, ?)
            """, (name, g_def["main_count"], g_def["main_range"], g_def["bonus_range"]))

        # prize_rules
        pr_count = db.execute("SELECT COUNT(*) AS c FROM prize_rules WHERE game_name=?", (name,)).fetchone()["c"]
        if pr_count == 0:
            for (main_m, bonus_m, prize) in g_def["prize_rules"]:
                db.execute("""
                    INSERT INTO prize_rules (game_name, main_matches, bonus_match, prize)
                    VALUES (?, ?, ?, ?)
                """, (name, main_m, 1 if bonus_m else 0, prize))

        # ticket_types
        tt_count = db.execute("SELECT COUNT(*) AS c FROM ticket_types WHERE game_name=?", (name,)).fetchone()["c"]
        if tt_count == 0:
            coming_sunday = next_sunday()
            db.execute("""
                        INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, winning_numbers, winning_bonus, is_active)
                        VALUES (?, ?, ?, ?, NULL, NULL, 1)
                    """, (name, g_def["price"], coming_sunday, g_def["prize_amount"]))

    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_sunday():
    today = datetime.now()
    days_ahead = 6 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def get_game_rule(game_name):
    db = get_db()
    return db.execute("SELECT * FROM game_rules WHERE game_name=?", (game_name,)).fetchone()


def get_prize_rules(game_name):
    db = get_db()
    return db.execute(
        "SELECT * FROM prize_rules WHERE game_name=? ORDER BY main_matches DESC, bonus_match DESC",
        (game_name,)
    ).fetchall()


def generate_ticket_numbers_for(main_count, main_range, bonus_range):
    main_nums = sorted(random.sample(range(1, main_range + 1), main_count))
    main_str = ",".join(map(str, main_nums))
    bonus_str = str(random.randint(1, bonus_range)) if bonus_range else None
    return main_str, bonus_str


def generate_ticket_numbers(game_name):
    rule = get_game_rule(game_name)
    if not rule:
        return ",".join(map(str, sorted(random.sample(range(1, 51), 5)))), None
    return generate_ticket_numbers_for(rule["main_count"], rule["main_range"], rule["bonus_range"])


def calc_prize(game_name, match_count, bonus_match):
    rules = get_prize_rules(game_name)
    for row in rules:
        if row["main_matches"] == match_count:
            if row["bonus_match"] == (1 if bonus_match else 0):
                return row["prize"]
    return 0.0


def evaluate_ticket(game_name, selected_numbers, selected_bonus, winning_numbers, winning_bonus):
    winning_set = set(winning_numbers.split(","))
    ticket_set = set(n.strip() for n in selected_numbers.split(","))
    match_count = len(ticket_set & winning_set)
    bonus_match = (str(selected_bonus) == str(winning_bonus)) if winning_bonus else False
    prize = calc_prize(game_name, match_count, bonus_match)
    is_winner = 1 if prize > 0 else 0
    result_status = "winning" if is_winner else "not_winning"
    return match_count, bonus_match, prize, is_winner, result_status


def generate_confirmation():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def auto_draw_if_needed():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    due = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 1 AND drawing_date <= ?
          AND (winning_numbers IS NULL OR winning_numbers = '')
    """, (today,)).fetchall()

    for game in due:
        main_str, bonus_str = generate_ticket_numbers(game["game_name"])
        db.execute("UPDATE ticket_types SET winning_numbers=?, winning_bonus=? WHERE id=?",
                   (main_str, bonus_str, game["id"]))

        pending = db.execute("""
            SELECT id, selected_numbers, selected_bonus FROM tickets
            WHERE ticket_type_id=? AND result_status='pending_drawing'
        """, (game["id"],)).fetchall()

        for t in pending:
            mc, bm, prize, iw, rs = evaluate_ticket(
                game["game_name"], t["selected_numbers"], t["selected_bonus"],
                main_str, bonus_str
            )
            db.execute("""
                UPDATE tickets SET match_count=?, bonus_match=?, winning_amount=?, is_winner=?, result_status=?
                WHERE id=?
            """, (mc, 1 if bm else 0, prize, iw, rs, t["id"]))

        db.commit()


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped_view


# ---------------------------------------------------------------------------
# Routes — public
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/init-db")
def initialize_database():
    try:
        init_db()
        ensure_default_games()
        flash("Database has been completely reset and initialized.")
    except Exception as e:
        flash(f"Initialization failed: {str(e)}")
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form["phone"].strip()
        address = request.form["address"].strip()
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        dateofbirth = request.form.get('dob')

        if not all([name, email, phone, address, password]):
            flash("All fields are required.")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for('register'))

        try:
            dob = datetime.strptime(dateofbirth, '%Y-%m-%d')

            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

            if age < 18:
                flash("You must be 18 years old or older to register.")
                return redirect(url_for("register"))

        except ValueError:
            flash("Invalid date format. Please use the date picker.")
            return redirect(url_for("register"))

        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("An account with that email already exists.")
            return redirect(url_for("register"))

        db.execute("""
            INSERT INTO users (name, email, phone, address, password_hash, role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, email, phone, address, generate_password_hash(password), "customer"))
        db.commit()
        flash("Registration successful. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["role"] = user["role"]
        flash("Logged in successfully.")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes — customer
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    auto_draw_if_needed()
    db = get_db()
    winning_count = db.execute("""
        SELECT COUNT(*) AS cnt FROM tickets t
        JOIN orders o ON t.order_id = o.id
        WHERE o.user_id=? AND t.is_winner=1
    """, (session["user_id"],)).fetchone()["cnt"]
    return render_template("dashboard.html", user_name=session.get("user_name"), winning_count=winning_count)


@app.route('/profile')
@login_required
def profile():
    db = get_db()

    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    return render_template("profile_page.html", user=user)

@app.route("/tickets")
@login_required
def tickets():
    db = get_db()
    tickets = db.execute("SELECT * FROM ticket_types WHERE is_active=1 ORDER BY game_name, drawing_date").fetchall()
    return render_template("tickets.html", tickets=tickets)


@app.route("/purchase/<int:ticket_type_id>", methods=["GET", "POST"])
@login_required
def purchase(ticket_type_id):
    db = get_db()
    ticket_type = db.execute(
        "SELECT * FROM ticket_types WHERE id=? AND is_active=1", (ticket_type_id,)
    ).fetchone()

    if ticket_type is None:
        flash("Ticket type not found.")
        return redirect(url_for("tickets"))

    game_name = ticket_type["game_name"]
    rule = get_game_rule(game_name)

    if request.method == "POST":
        try:
            quantity = int(request.form["quantity"])
        except ValueError:
            flash("Quantity must be a valid number.")
            return redirect(url_for("purchase", ticket_type_id=ticket_type_id))

        selection_mode = request.form["selection_mode"]

        if quantity < 1 or quantity > 10:
            flash("You may only purchase between 1 and 10 tickets.")
            return redirect(url_for("purchase", ticket_type_id=ticket_type_id))

        manual_main = None
        manual_bonus = None
        if selection_mode == "manual":
            manual_main = request.form.get("manual_numbers", "").strip()
            manual_bonus = request.form.get("manual_bonus", "").strip() or None
            if not manual_main:
                flash("Please enter your numbers.")
                return redirect(url_for("purchase", ticket_type_id=ticket_type_id))

        total_amount = ticket_type["price"] * quantity
        tickets_list = []
        for _ in range(quantity):
            if selection_mode == "auto":
                main_str, bonus_str = generate_ticket_numbers(game_name)
            else:
                main_str, bonus_str = manual_main, manual_bonus
            tickets_list.append((main_str, bonus_str))

        session["pending_order"] = {
            "ticket_type_id": ticket_type_id,
            "game_name": game_name,
            "quantity": quantity,
            "selection_mode": selection_mode,
            "total_amount": total_amount,
            "tickets_list": tickets_list,
        }
        return redirect(url_for("payment"))

    return render_template("purchase.html", ticket=ticket_type, rule=rule)


@app.route("/payment", methods=["GET", "POST"])
@login_required
def payment():
    order = session.get("pending_order")
    if not order:
        flash("No pending order.")
        return redirect(url_for("tickets"))

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        db = get_db()

        cursor = db.execute("""
            INSERT INTO orders (user_id, order_date, total_amount, status)
            VALUES (?, ?, ?, ?)
        """, (session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order["total_amount"], "completed"))
        order_id = cursor.lastrowid

        for (main_nums, bonus_num) in order["tickets_list"]:
            db.execute("""
                INSERT INTO tickets
                (order_id, ticket_type_id, selected_numbers, selected_bonus, selection_mode, confirmation_number)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
            order_id, order["ticket_type_id"], main_nums, bonus_num, order["selection_mode"], generate_confirmation()))

        db.execute("""
            INSERT INTO payments (order_id, payment_method, amount, payment_status, transaction_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
        order_id, payment_method, order["total_amount"], "approved", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        db.commit()
        session.pop("pending_order", None)
        flash("Purchase successful!")
        return redirect(url_for("orders"))

    return render_template("payment.html", total_amount=order["total_amount"])


@app.route("/orders")
@login_required
def orders():
    db = get_db()
    orders = db.execute("""
        SELECT * FROM orders WHERE user_id=? ORDER BY order_date DESC
    """, (session["user_id"],)).fetchall()
    tickets = db.execute("""
        SELECT t.*, tt.game_name FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE o.user_id=? ORDER BY o.order_date DESC, t.id DESC
    """, (session["user_id"],)).fetchall()
    return render_template("orders.html", orders=orders, tickets=tickets)


@app.route("/winning-numbers")
def winning_numbers():
    db = get_db()
    games = db.execute("SELECT * FROM ticket_types WHERE is_active=1 ORDER BY drawing_date ASC").fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("winning_numbers.html", games=games, today=today,
                           check_result=None, check_error=None, check_confirmation=None)


@app.route("/claim/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def claim_ticket(ticket_id):
    db = get_db()
    # Fetch ticket data only if it is a winning ticket and not yet claimed
    ticket = db.execute("""
        SELECT t.*, t.winning_amount 
        FROM tickets t 
        WHERE t.id = ? AND t.is_winner = 1 AND t.claim_status = 'not_claimed'
    """, (ticket_id,)).fetchone()

    if not ticket:
        flash("Invalid request or ticket already claimed.")
        return redirect(url_for("orders"))

    # Logic for Small Prizes ($599 or less)
    if ticket["winning_amount"] <= 599:
        if request.method == "POST":
            method = request.form.get("payment_method")
            # Update status and payout type for small prizes
            db.execute("UPDATE tickets SET claim_status='claimed', payout_type='small' WHERE id=?", (ticket_id,))
            db.commit()
            flash(f"Claim processed. ${ticket['winning_amount'] * 0.76:.2f} (Tax 24% deducted) sent to {method}.")
            return redirect(url_for("orders"))
        return render_template("claim_small.html", ticket=ticket)

    # Logic for Large Prizes (Over $599)
    else:
        # Generate a unique 20-character claim code if not already generated
        if not ticket["claim_code"]:
            new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=20))
            db.execute("UPDATE tickets SET claim_code=?, claim_status='claimed', payout_type='large' WHERE id=?",
                       (new_code, ticket_id))
            db.commit()
            # Re-fetch ticket to include the new claim_code
            ticket = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()

        # Calculate expiration date (1 year from drawing date)
        draw_info = db.execute("SELECT drawing_date FROM ticket_types WHERE id=?",
                               (ticket['ticket_type_id'],)).fetchone()
        draw_date = datetime.strptime(draw_info['drawing_date'], "%Y-%m-%d")
        exp_date = (draw_date + timedelta(days=365)).strftime("%Y-%m-%d")

        return render_template("claim_large.html", ticket=ticket, exp_date=exp_date)

@app.route("/winning-numbers/check", methods=["POST"])
@login_required
def check_ticket():
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    confirmation = request.form.get("confirmation_number", "").strip().upper()
    games = db.execute("SELECT * FROM ticket_types WHERE is_active=1 ORDER BY drawing_date ASC").fetchall()

    if not confirmation:
        return render_template("winning_numbers.html", games=games, today=today,
                               check_result=None, check_error="Please enter a confirmation number.",
                               check_confirmation=confirmation)

    row = db.execute("""
        SELECT t.confirmation_number, t.is_winner, t.claim_status,
               t.match_count, t.bonus_match, t.winning_amount, tt.game_name
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE t.confirmation_number=? AND o.user_id=?
    """, (confirmation, session["user_id"])).fetchone()

    if row is None:
        return render_template("winning_numbers.html", games=games, today=today,
                               check_result=None,
                               check_error="No ticket found with that confirmation number.",
                               check_confirmation=confirmation)

    return render_template("winning_numbers.html", games=games, today=today,
                           check_result=row, check_error=None, check_confirmation=confirmation)


@app.route("/search")
@login_required
def search():
    query = request.args.get("query", "").strip()
    tickets = []
    if query:
        db = get_db()
        tickets = db.execute("""
            SELECT t.*, tt.game_name, o.order_date FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE o.user_id=? AND (tt.game_name LIKE ? OR t.confirmation_number LIKE ?)
            ORDER BY o.order_date DESC
        """, (session["user_id"], f"%{query}%", f"%{query}%")).fetchall()
    return render_template("search.html", tickets=tickets, query=query)


# ---------------------------------------------------------------------------
# Routes — admin
# ---------------------------------------------------------------------------
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    tickets = db.execute("SELECT * FROM ticket_types ORDER BY game_name, drawing_date").fetchall()
    game_rules = db.execute("SELECT * FROM game_rules ORDER BY game_name").fetchall()
    return render_template("admin.html", tickets=tickets, game_rules=game_rules)


# --- Game rule CRUD ---
@app.route("/admin/game/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_game():
    if request.method == "POST":
        name = request.form["game_name"].strip()
        main_count = int(request.form["main_count"])
        main_range = int(request.form["main_range"])
        bonus_range = request.form.get("bonus_range", "").strip()
        bonus_range = int(bonus_range) if bonus_range else None

        db = get_db()
        if db.execute("SELECT id FROM game_rules WHERE game_name=?", (name,)).fetchone():
            flash("A game with that name already exists.")
            return redirect(url_for("admin_add_game"))

        db.execute("""
            INSERT INTO game_rules (game_name, main_count, main_range, bonus_range)
            VALUES (?, ?, ?, ?)
        """, (name, main_count, main_range, bonus_range))
        db.commit()
        flash(f"Game '{name}' created! Now add prize rules and create a ticket type.")
        return redirect(url_for("admin_prize_rules", game_name=name))

    return render_template("admin_add_game.html")

@app.route("/admin/verify-ticket", methods=["GET", "POST"])
@login_required
@admin_required
def verify_ticket():
    result = None
    if request.method == "POST":
        code = request.form.get("verify_code").strip()
        db = get_db()
        # Verify using either the 20-char claim code or the original confirmation number
        result = db.execute("""
            SELECT t.*, u.name as user_name, tt.game_name 
            FROM tickets t
            JOIN orders o ON t.order_id = o.id
            JOIN users u ON o.user_id = u.id
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            WHERE t.claim_code = ? OR t.confirmation_number = ?
        """, (code, code)).fetchone()
    return render_template("admin_verify.html", result=result)

@app.route("/admin/game/edit/<game_name>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_game(game_name):
    db = get_db()
    rule = db.execute("SELECT * FROM game_rules WHERE game_name=?", (game_name,)).fetchone()

    if request.method == "POST":
        main_count = int(request.form["main_count"])
        main_range = int(request.form["main_range"])
        bonus_range = request.form.get("bonus_range", "").strip()
        bonus_range = int(bonus_range) if bonus_range else None

        db.execute("""
            UPDATE game_rules SET main_count=?, main_range=?, bonus_range=? WHERE game_name=?
        """, (main_count, main_range, bonus_range, game_name))
        db.commit()
        flash("Game rule updated!")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_edit_game.html", rule=rule)


@app.route("/admin/game/delete/<game_name>", methods=["POST"])
@login_required
@admin_required
def admin_delete_game(game_name):
    db = get_db()
    db.execute("DELETE FROM game_rules WHERE game_name=?", (game_name,))
    db.execute("DELETE FROM prize_rules WHERE game_name=?", (game_name,))
    db.execute("UPDATE ticket_types SET is_active=0 WHERE game_name=?", (game_name,))
    db.commit()
    flash(f"Game '{game_name}' deleted.")
    return redirect(url_for("admin_dashboard"))


# --- Prize rule CRUD ---
@app.route("/admin/prize-rules/<game_name>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_prize_rules(game_name):
    db = get_db()
    rule = db.execute("SELECT * FROM game_rules WHERE game_name=?", (game_name,)).fetchone()
    rows = get_prize_rules(game_name)

    if request.method == "POST":
        main_matches = int(request.form["main_matches"])
        bonus_match = 1 if request.form.get("bonus_match") else 0
        prize = float(request.form["prize"])

        db.execute("""
            INSERT INTO prize_rules (game_name, main_matches, bonus_match, prize)
            VALUES (?, ?, ?, ?)
        """, (game_name, main_matches, bonus_match, prize))
        db.commit()
        flash("Prize rule added!")
        return redirect(url_for("admin_prize_rules", game_name=game_name))

    return render_template("admin_prize_rules.html", game_name=game_name, rule=rule, rows=rows)


@app.route("/admin/prize-rules/edit/<int:rule_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_prize_rule(rule_id):
    db = get_db()
    row = db.execute("SELECT * FROM prize_rules WHERE id=?", (rule_id,)).fetchone()

    if request.method == "POST":
        prize = float(request.form["prize"])
        db.execute("UPDATE prize_rules SET prize=? WHERE id=?", (prize, rule_id))
        db.commit()
        flash("Prize updated!")
        return redirect(url_for("admin_prize_rules", game_name=row["game_name"]))

    return render_template("admin_edit_prize_rule.html", row=row)


@app.route("/admin/prize-rules/delete/<int:rule_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_prize_rule(rule_id):
    db = get_db()
    row = db.execute("SELECT * FROM prize_rules WHERE id=?", (rule_id,)).fetchone()
    game_name = row["game_name"]
    db.execute("DELETE FROM prize_rules WHERE id=?", (rule_id,))
    db.commit()
    flash("Prize rule deleted.")
    return redirect(url_for("admin_prize_rules", game_name=game_name))


# --- Ticket type CRUD ---
@app.route("/admin/ticket/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_ticket():
    db = get_db()
    game_rules = db.execute("SELECT * FROM game_rules ORDER BY game_name").fetchall()

    if request.method == "POST":
        game_name = request.form["game_name"]
        price = float(request.form["price"])
        drawing_date = request.form["drawing_date"]
        prize_amount = float(request.form["prize_amount"])

        db.execute("""
            INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (game_name, price, drawing_date, prize_amount))
        db.commit()
        flash("Ticket type added!")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_add_ticket.html", game_rules=game_rules)


@app.route("/admin/ticket/edit/<int:ticket_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_ticket(ticket_id):
    db = get_db()
    ticket = db.execute("SELECT * FROM ticket_types WHERE id=?", (ticket_id,)).fetchone()

    if request.method == "POST":
        price = float(request.form["price"])
        drawing_date = request.form["drawing_date"]
        prize_amount = float(request.form["prize_amount"])
        active = int(request.form["is_active"])

        db.execute("""
            UPDATE ticket_types SET price=?, drawing_date=?, prize_amount=?, is_active=?
            WHERE id=?
        """, (price, drawing_date, prize_amount, active, ticket_id))
        db.commit()
        flash("Ticket updated!")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_ticket.html", ticket=ticket)


@app.route("/admin/ticket/delete/<int:ticket_id>", methods=["POST"])
@login_required
@admin_required
def delete_ticket(ticket_id):
    db = get_db()
    db.execute("UPDATE ticket_types SET is_active=0 WHERE id=?", (ticket_id,))
    db.commit()
    flash("Ticket removed from active listings.")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/finalize/<int:ticket_type_id>", methods=["POST"])
@login_required
@admin_required
def finalize_drawing(ticket_type_id):
    db = get_db()
    game = db.execute("SELECT * FROM ticket_types WHERE id=?", (ticket_type_id,)).fetchone()

    if game["winning_numbers"]:
        main_str = game["winning_numbers"]
        bonus_str = game["winning_bonus"]
    else:
        main_str, bonus_str = generate_ticket_numbers(game["game_name"])
        db.execute("UPDATE ticket_types SET winning_numbers=?, winning_bonus=? WHERE id=?",
                   (main_str, bonus_str, ticket_type_id))

    pending = db.execute("""
        SELECT id, selected_numbers, selected_bonus FROM tickets
        WHERE ticket_type_id=? AND result_status='pending_drawing'
    """, (ticket_type_id,)).fetchall()

    winner_count = 0
    for t in pending:
        mc, bm, prize, iw, rs = evaluate_ticket(
            game["game_name"], t["selected_numbers"], t["selected_bonus"], main_str, bonus_str
        )
        payout_type = "small" if prize <= 599 else "large"

        db.execute("""
            UPDATE tickets SET match_count=?, bonus_match=?, winning_amount=?, is_winner=?, result_status=?, payout_type=?
            WHERE id=?
        """, (mc, 1 if bm else 0, prize, iw, rs, payout_type, t["id"]))
        if iw:
            winner_count += 1

    db.execute("UPDATE ticket_types SET drawing_date=?, winning_numbers=NULL, winning_bonus=NULL WHERE id=?",
               (next_sunday(), ticket_type_id))
    db.commit()

    bonus_display = f" + Bonus: {bonus_str}" if bonus_str else ""
    flash(f"Drawing finalized. Winning: {main_str}{bonus_display}. {winner_count} winner(s).")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/generate-report", methods=["POST"])
@login_required
@admin_required
def generate_report():
    db = get_db()

    # Ensure reports table exists (for existing DBs that predate the schema update)
    db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_by TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            total_revenue REAL NOT NULL,
            report_data TEXT NOT NULL
        )
    """)

    # Total revenue from all approved payments
    total_revenue = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE payment_status = 'approved'"
    ).fetchone()["total"]

    # Tickets sold per game
    ticket_sales = db.execute("""
        SELECT tt.game_name, tt.price, COUNT(t.id) AS tickets_sold,
               COUNT(t.id) * tt.price AS game_revenue
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        GROUP BY tt.id, tt.game_name, tt.price
        ORDER BY tickets_sold DESC
    """).fetchall()

    import json
    sales_data = [
        {
            "game_name": row["game_name"],
            "price": row["price"],
            "tickets_sold": row["tickets_sold"],
            "game_revenue": row["game_revenue"],
        }
        for row in ticket_sales
    ]

    admin_name = db.execute(
        "SELECT name FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()["name"]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        "INSERT INTO reports (generated_by, generated_at, total_revenue, report_data) VALUES (?, ?, ?, ?)",
        (admin_name, generated_at, total_revenue, json.dumps(sales_data)),
    )
    db.commit()

    flash("Report generated successfully.")
    return redirect(url_for("view_report"))


@app.route("/admin/report")
@login_required
@admin_required
def view_report():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_by TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            total_revenue REAL NOT NULL,
            report_data TEXT NOT NULL
        )
    """)

    report = db.execute(
        "SELECT * FROM reports ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if report is None:
        return render_template("report.html", report=None)

    import json
    sales_data = json.loads(report["report_data"])
    return render_template("report.html", report=report, sales_data=sales_data)


# ---------------------------------------------------------------------------
# Startup seed
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(debug=True)