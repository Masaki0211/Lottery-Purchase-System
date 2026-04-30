import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
from functools import wraps

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
# Rules: all games pick 5 numbers from 1-50, once per week
# Prize = % of jackpot based on matches
# ---------------------------------------------------------------------------

PRIZE_PERCENTAGES = {5: 1.0, 4: 0.20, 3: 0.05, 2: 0.01, 1: 0.0, 0: 0.0}

DEFAULT_GAMES = [
    {"game_name": "Power Ball",     "price": 2.00, "prize_amount": 1000000.00},
    {"game_name": "Mega Millions",  "price": 2.00, "prize_amount": 2000000.00},
    {"game_name": "Lotto Texas",    "price": 1.00, "prize_amount":  500000.00},
    {"game_name": "Texas Two Step", "price": 1.50, "prize_amount":  250000.00},
]

def calc_prize(match_count, prize_amount):
    pct = PRIZE_PERCENTAGES.get(match_count, 0.0)
    return round(prize_amount * pct, 2)

def generate_numbers():
    nums = sorted(random.sample(range(1, 51), 5))
    return ",".join(map(str, nums))

def generate_confirmation():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def get_target_sunday(base_date):
    """"""
    base_date = datetime.strptime(base_date, "%Y-%m-%d")
    days_until_sunday = 6 - base_date.weekday()
    target_sunday = base_date + timedelta(days=days_until_sunday)

    return target_sunday.strftime("%Y-%m-%d")

def next_drawing_date(base_date):
    base = datetime.strptime(base_date, "%Y-%m-%d")
    return (base + timedelta(days=7)).strftime("%Y-%m-%d")

def ensure_default_games():
    """Seed default 4 games on startup if DB is empty. Comment out body to disable."""
    db = get_db()
    today = datetime.now().strftime("Y-%m-%d")
    first_sunday = get_target_sunday(today)

    for g_def in DEFAULT_GAMES:
        name = g_def["game_name"]
        tt_count = db.execute(
            "SELECT COUNT(*) AS c FROM ticket_types WHERE game_name=?", (name,)
        ).fetchone()["c"]
        if tt_count == 0:
            db.execute("""
                    INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, is_active)
                    VALUES (?, ?, ?, ?, 1)
                """, (name, g_def["price"], first_sunday, g_def["prize_amount"]))
    db.commit()


def evaluate_ticket(selected_numbers, winning_numbers, prize_amount):
    winning_set = set(winning_numbers.split(","))
    ticket_set = set(n.strip() for n in selected_numbers.split(","))
    match_count = len(ticket_set & winning_set)
    prize = calc_prize(match_count, prize_amount)
    is_winner = 1 if prize > 0 else 0
    result_status = "winning" if is_winner else "not_winning"
    return match_count, prize, is_winner, result_status


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
            INSERT INTO users (name, email, phone, address, password_hash, role, dob)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email, phone, address, generate_password_hash(password), "customer", dateofbirth))
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

        tickets_list = []
        for i in range(quantity):
            if selection_mode == "auto":
                tickets_list.append(generate_numbers())
            else:
                manual = request.form.get(f"manual_numbers_{i}", "").strip()
                if not manual:
                    flash(f"Please enter numbers for ticket {i + 1}.")
                    return redirect(url_for("purchase", ticket_type_id=ticket_type_id))
                tickets_list.append(manual)

        session["pending_order"] = {
            "ticket_type_id": ticket_type_id,
            "game_name": ticket_type["game_name"],
            "quantity": quantity,
            "selection_mode": selection_mode,
            "total_amount": ticket_type["price"] * quantity,
            "tickets_list": tickets_list,
        }
        return redirect(url_for("payment"))

    return render_template("purchase.html", ticket=ticket_type)

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

        for numbers in order["tickets_list"]:
            db.execute("""
                        INSERT INTO tickets
                        (order_id, ticket_type_id, selected_numbers, selection_mode, confirmation_number)
                        VALUES (?, ?, ?, ?, ?)
                    """, (order_id, order["ticket_type_id"], numbers,
                          order["selection_mode"], generate_confirmation()))

        db.execute("""
                    INSERT INTO payments (order_id, payment_method, amount, payment_status, transaction_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (order_id, payment_method, order["total_amount"], "approved",
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

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
            SELECT t.*, tt.game_name, tt.prize_amount FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE o.user_id=? ORDER BY o.order_date DESC, t.id DESC
        """, (session["user_id"],)).fetchall()
    return render_template("orders.html", orders=orders, tickets=tickets)


@app.route("/winning-numbers")
def winning_numbers():
    db = get_db()
    active_games = db.execute(
        "SELECT * FROM ticket_types WHERE is_active=1 ORDER BY drawing_date ASC"
    ).fetchall()
    past_games = db.execute("""
        SELECT t1.* FROM ticket_types t1
        WHERE t1.is_active=0 AND t1.winning_numbers IS NOT NULL
          AND t1.id = (
            SELECT t2.id FROM ticket_types t2
            WHERE t2.game_name = t1.game_name AND t2.winning_numbers IS NOT NULL
            ORDER BY t2.drawing_date DESC LIMIT 1
          )
        ORDER BY t1.game_name
    """).fetchall()
    return render_template("winning_numbers.html",
                           active_games=active_games, past_games=past_games,
                           check_result=None, check_error=None, check_confirmation=None)


@app.route("/claim/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def claim_ticket(ticket_id):
    db = get_db()
    ticket = db.execute("""
            SELECT t.*, tt.prize_amount, tt.drawing_date, tt.game_name
            FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            WHERE t.id=? AND t.is_winner=1 AND t.claim_status='not_claimed'
        """, (ticket_id,)).fetchone()

    if not ticket:
        flash("Invalid request or ticket already claimed.")
        return redirect(url_for("orders"))

    if ticket["winning_amount"] <= 599:
        if request.method == "POST":
            method = request.form.get("payment_method")
            db.execute(
                "UPDATE tickets SET claim_status='claimed', payout_type='small' WHERE id=?",
                (ticket_id,)
            )
            db.commit()
            net = ticket["winning_amount"] * 0.76
            flash(f"Claim processed! ${net:.2f} (after 24% tax) sent to {method}.")
            return redirect(url_for("orders"))
        return render_template("claim_small.html", ticket=ticket)
    else:
        if not ticket["claim_code"]:
            new_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
            db.execute(
                "UPDATE tickets SET claim_code=?, claim_status='claimed', payout_type='large' WHERE id=?",
                (new_code, ticket_id)
            )
            db.commit()
            ticket = db.execute("""
                    SELECT t.*, tt.prize_amount, tt.drawing_date, tt.game_name
                    FROM tickets t
                    JOIN ticket_types tt ON t.ticket_type_id = tt.id
                    WHERE t.id=?
                """, (ticket_id,)).fetchone()

        draw_date = datetime.strptime(ticket["drawing_date"], "%Y-%m-%d")
        exp_date = (draw_date + timedelta(days=365)).strftime("%Y-%m-%d")
        return render_template("claim_large.html", ticket=ticket, exp_date=exp_date)

@app.route("/winning-numbers/check", methods=["POST"])
@login_required
def check_ticket():
    db = get_db()
    confirmation = request.form.get("confirmation_number", "").strip().upper()
    active_games = db.execute(
        "SELECT * FROM ticket_types WHERE is_active=1 ORDER BY drawing_date ASC"
    ).fetchall()
    past_games = db.execute("""
        SELECT t1.* FROM ticket_types t1
        WHERE t1.is_active=0 AND t1.winning_numbers IS NOT NULL
          AND t1.id = (
            SELECT t2.id FROM ticket_types t2
            WHERE t2.game_name = t1.game_name AND t2.winning_numbers IS NOT NULL
            ORDER BY t2.drawing_date DESC LIMIT 1
          )
        ORDER BY t1.game_name
    """).fetchall()

    if not confirmation:
        return render_template("winning_numbers.html", active_games=active_games, past_games=past_games,
                               check_result=None,
                               check_error="Please enter a confirmation number.",
                               check_confirmation=confirmation)

    row = db.execute("""
            SELECT t.confirmation_number, t.is_winner, t.claim_status,
                   t.match_count, t.winning_amount, tt.game_name
            FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE t.confirmation_number=? AND o.user_id=?
        """, (confirmation, session["user_id"])).fetchone()

    if row is None:
        return render_template("winning_numbers.html", active_games=active_games, past_games=past_games,
                               check_result=None,
                               check_error="No ticket found with that confirmation number.",
                               check_confirmation=confirmation)

    return render_template("winning_numbers.html", active_games=active_games, past_games=past_games,
                           check_result=row, check_error=None,
                           check_confirmation=confirmation)


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
    tickets = db.execute("SELECT * FROM ticket_types WHERE is_active=1 ORDER BY game_name, drawing_date").fetchall()
    return render_template("admin.html", tickets=tickets)


@app.route("/admin/verify-ticket", methods=["GET", "POST"])
@login_required
@admin_required
def verify_ticket():
    result = None
    if request.method == "POST":
        code = request.form.get("verify_code", "").strip()
        db = get_db()
        result = db.execute("""
                SELECT t.*, u.name as user_name, tt.game_name, tt.drawing_date, tt.prize_amount
                FROM tickets t
                JOIN orders o ON t.order_id = o.id
                JOIN users u ON o.user_id = u.id
                JOIN ticket_types tt ON t.ticket_type_id = tt.id
                WHERE t.claim_code=? OR t.confirmation_number=?
            """, (code, code)).fetchone()
    return render_template("admin_verify.html", result=result)



# --- Ticket type CRUD ---
@app.route("/admin/ticket/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_ticket():
    if request.method == "POST":
        game_name = request.form["game_name"].strip()
        price = float(request.form["price"])
        drawing_date = request.form["drawing_date"]
        prize_amount = float(request.form["prize_amount"])

        db = get_db()
        db.execute("""
                INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (game_name, price, drawing_date, prize_amount))
        db.commit()
        flash("Ticket type added!")
        return redirect(url_for("admin_dashboard"))

    game_names = [g["game_name"] for g in DEFAULT_GAMES]
    return render_template("admin_add_ticket.html", game_names=game_names)


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

    winning_str = game["winning_numbers"] or generate_numbers()
    if not game["winning_numbers"]:
        db.execute("UPDATE ticket_types SET winning_numbers=? WHERE id=?",
                   (winning_str, ticket_type_id))

    pending = db.execute("""
            SELECT id, selected_numbers FROM tickets
            WHERE ticket_type_id=? AND result_status='pending_drawing'
        """, (ticket_type_id,)).fetchall()

    winner_count = 0
    for t in pending:
        mc, prize, iw, rs = evaluate_ticket(
            t["selected_numbers"], winning_str, game["prize_amount"]
        )
        payout_type = "small" if 0 < prize <= 599 else ("large" if prize > 599 else "none")
        db.execute("""
                UPDATE tickets SET match_count=?, winning_amount=?, is_winner=?, result_status=?, payout_type=?
                WHERE id=?
            """, (mc, prize, iw, rs, payout_type, t["id"]))
        if iw:
            winner_count += 1

    # Create next week's ticket type
    db.execute("""
            INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (game["game_name"], game["price"], next_drawing_date(game["drawing_date"]), game["prize_amount"]))

    # Deactivate old one
    db.execute("UPDATE ticket_types SET is_active=0 WHERE id=?", (ticket_type_id,))
    db.commit()

    flash(f"Drawing finalized. Winning numbers: {winning_str}. {winner_count} winner(s).")
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