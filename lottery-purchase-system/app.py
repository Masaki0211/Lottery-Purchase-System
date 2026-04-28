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
    with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()

def next_sunday():
    today = datetime.now()
    days_ahead = 6 - today.weekday()  # Sunday = 6
    if days_ahead <= 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

def seed_ticket_types():
    db = get_db()
    existing = db.execute("SELECT COUNT(*) AS count FROM ticket_types").fetchone()["count"]

    if existing == 0:
        last_sunday = (datetime.now() - timedelta(days=datetime.now().weekday() + 1)).strftime("%Y-%m-%d")
        coming_sunday = next_sunday()

        sample_tickets = [
            # last week (result)
            (
            "Power Ball", 2.00, last_sunday, 1000000.00, ",".join(map(str, sorted(random.sample(range(1, 51), 5)))), 1),
            ("Mega Millions", 2.00, last_sunday, 2000000.00, ",".join(map(str, sorted(random.sample(range(1, 51), 5)))),
             1),
            (
            "Lotto Texas", 1.00, last_sunday, 500000.00, ",".join(map(str, sorted(random.sample(range(1, 51), 5)))), 1),
            ("Texas Two Step", 1.50, last_sunday, 250000.00, ",".join(map(str, sorted(random.sample(range(1, 51), 5)))),
             1),
            # this week (pending)
            ("Power Ball", 2.00, coming_sunday, 1000000.00, None, 1),
            ("Mega Millions", 2.00, coming_sunday, 2000000.00, None, 1),
            ("Lotto Texas", 1.00, coming_sunday, 500000.00, None, 1),
            ("Texas Two Step", 1.50, coming_sunday, 250000.00, None, 1),
        ]

        db.executemany("""
            INSERT INTO ticket_types
            (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sample_tickets)
        db.commit()

    # ------------------------------------------------------
    # Prize logic per game
    # ------------------------------------------------------

PRIZE_RULES = {
        "Power Ball": [
            (5, 1000000.00),
            (4, 50000.00),
            (3, 100.00),
            (2, 7.00),
            (1, 4.00),
        ],
        "Mega Millions": [
            (5, 2000000.00),
            (4, 10000.00),
            (3, 200.00),
            (2, 10.00),
            (1, 4.00),
        ],
        "Lotto Texas": [
            (5, 500000.00),
            (4, 5000.00),
            (3, 50.00),
            (2, 2.00),
            (1, 0.00),
        ],
        "Texas Two Step": [
            (5, 250000.00),
            (4, 1000.00),
            (3, 25.00),
            (2, 2.00),
            (1, 0.00),
        ],
    }

def calc_prize(game_name, match_count):
    rules = PRIZE_RULES.get(game_name, [])
    for (matches, prize) in rules:
        if match_count >= matches:
            return prize
    return 0.0

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


# Weekly auto-draw
def auto_draw_if_needed():
    """
    For every active ticket type whose drawing_date has passed
    and winning_numbers is still NULL, generate numbers automatically,
    evaluate all tickets, then set the next drawing date to the following Sunday.
    """
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    due = db.execute("""
            SELECT * FROM ticket_types
            WHERE is_active = 1
              AND drawing_date <= ?
              AND (winning_numbers IS NULL OR winning_numbers = '')
        """, (today,)).fetchall()

    for game in due:
        nums = sorted(random.sample(range(1, 51), 5))
        winning_str = ",".join(map(str, nums))
        winning_set = set(map(str, nums))

        db.execute("UPDATE ticket_types SET winning_numbers = ? WHERE id = ?",
                   (winning_str, game["id"]))

        # Evaluate every ticket for this game
        tickets = db.execute("""
                SELECT t.id, t.selected_numbers
                FROM tickets t
                WHERE t.ticket_type_id = ?
                  AND t.result_status = 'pending_drawing'
            """, (game["id"],)).fetchall()

        for ticket in tickets:
            ticket_nums = set(n.strip() for n in ticket["selected_numbers"].split(","))
            match_count = len(ticket_nums & winning_set)
            prize = calc_prize(game["game_name"], match_count)
            is_winner = 1 if prize > 0 else 0
            result_status = "winning" if is_winner else "not_winning"

            db.execute("""
                    UPDATE tickets
                    SET match_count = ?, winning_amount = ?, is_winner = ?, result_status = ?
                    WHERE id = ?
                """, (match_count, prize, is_winner, result_status, ticket["id"]))

        db.commit()

def generate_numbers(mode, manual_pick=None):
    if mode == "auto":
        nums = sorted(random.sample(range(1, 51), 5))
        return ",".join(map(str, nums))
    else:
        return manual_pick


def generate_confirmation():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/init-db")
def initialize_database():
    init_db()
    seed_ticket_types()
    flash("Database initialized successfully.")
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form["phone"].strip()
        address = request.form["address"].strip()
        password = request.form["password"]

        if not name or not email or not phone or not address or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        db = get_db()
        existing_user = db.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing_user:
            flash("An account with that email already exists.")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        db.execute("""
            INSERT INTO users (name, email, phone, address, password_hash, role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, email, phone, address, password_hash, "customer"))
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
        user = db.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

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


@app.route("/dashboard")
@login_required
def dashboard():
    auto_draw_if_needed()
    db = get_db()
    winning_count = db.execute("""
            SELECT COUNT(*) AS cnt FROM tickets t
            JOIN orders o ON t.order_id = o.id
            WHERE o.user_id = ? AND t.is_winner = 1
        """, (session["user_id"],)).fetchone()["cnt"]

    return render_template("dashboard.html",
                           user_name=session.get("user_name"),
                           winning_count=winning_count)


@app.route("/tickets")
@login_required
def tickets():
    db = get_db()
    tickets = db.execute(
        "SELECT * FROM ticket_types WHERE is_active = 1"
    ).fetchall()
    return render_template("tickets.html", tickets=tickets)


@app.route("/purchase/<int:ticket_type_id>", methods=["GET", "POST"])
@login_required
def purchase(ticket_type_id):
    db = get_db()

    ticket_type = db.execute(
        "SELECT * FROM ticket_types WHERE id = ? AND is_active = 1",
        (ticket_type_id,)
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

        if selection_mode not in ["auto", "manual"]:
            flash("Invalid selection mode.")
            return redirect(url_for("purchase", ticket_type_id=ticket_type_id))

        manual_picks = []
        if selection_mode == "manual":
            raw = request.form.get("manual_numbers", "").strip()
            if not raw:
                flash("숫자를 입력해주세요.")
                return redirect(url_for("purchase", ticket_type_id=ticket_type_id))
            manual_picks = [raw] * quantity

        total_amount = ticket_type["price"] * quantity
        numbers_list = [
            generate_numbers(selection_mode, manual_picks[i] if manual_picks else None)
            for i in range(quantity)
        ]

        session["pending_order"] = {
            "ticket_type_id": ticket_type_id,
            "quantity": quantity,
            "selection_mode": selection_mode,
            "total_amount": total_amount,
            "numbers_list": numbers_list,
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
        """, (
            session["user_id"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order["total_amount"],
            "completed"
        ))
        order_id = cursor.lastrowid

        for numbers in order["numbers_list"]:
            db.execute("""
                INSERT INTO tickets
                (order_id, ticket_type_id, selected_numbers, selection_mode, confirmation_number)
                VALUES (?, ?, ?, ?, ?)
            """, (
                order_id,
                order["ticket_type_id"],
                numbers,
                order["selection_mode"],
                generate_confirmation()
            ))

        db.execute("""
            INSERT INTO payments (order_id, payment_method, amount, payment_status, transaction_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            order_id,
            payment_method,
            order["total_amount"],
            "approved",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

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
        SELECT * FROM orders
        WHERE user_id = ?
        ORDER BY order_date DESC
    """, (session["user_id"],)).fetchall()

    tickets = db.execute("""
        SELECT t.*, tt.game_name
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE o.user_id = ?
        ORDER BY o.order_date DESC, t.id DESC
    """, (session["user_id"],)).fetchall()

    return render_template("orders.html", orders=orders, tickets=tickets)

def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped_view

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    db = get_db()

    tickets = db.execute("SELECT * FROM ticket_types").fetchall()

    return render_template("admin.html", tickets=tickets)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))

@app.route("/admin/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_ticket():
    if request.method == "POST":
        name = request.form["game_name"]
        price = float(request.form["price"])
        date = request.form["drawing_date"]
        prize = float(request.form["prize_amount"])
        winning = request.form.get("winning_numbers", "").strip() or None

        db = get_db()
        db.execute("""
            INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (name, price, date, prize, winning))
        db.commit()

        flash("Ticket added!")
        return redirect(url_for("admin_dashboard"))

    return render_template("add_ticket.html")


@app.route("/admin/edit/<int:ticket_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_ticket(ticket_id):
    db = get_db()
    ticket = db.execute("SELECT * FROM ticket_types WHERE id = ?", (ticket_id,)).fetchone()

    if request.method == "POST":
        name = request.form["game_name"]
        price = float(request.form["price"])
        date = request.form["drawing_date"]
        prize = float(request.form["prize_amount"])
        active = int(request.form["is_active"])
        winning = request.form.get("winning_numbers", "").strip() or None

        db.execute("""
                UPDATE ticket_types
                SET game_name=?, price=?, drawing_date=?, prize_amount=?, is_active=?, winning_numbers=?
                WHERE id=?
            """, (name, price, date, prize, active, winning, ticket_id))
        db.commit()
        flash("Updated!")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_ticket.html", ticket=ticket)

@app.route("/admin/delete/<int:ticket_id>", methods=["POST"])
@login_required
@admin_required
def delete_ticket(ticket_id):
    db = get_db()

    db.execute("""
        UPDATE ticket_types
        SET is_active = 0
        WHERE id = ?
    """, (ticket_id,))
    db.commit()

    flash("Ticket removed from active listings.")
    return redirect(url_for("admin_dashboard"))



@app.route("/winning-numbers", methods=["GET"])
def winning_numbers():
    db = get_db()
    games = db.execute(
        "SELECT * FROM ticket_types WHERE is_active = 1 ORDER BY drawing_date ASC"
    ).fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("winning_numbers.html", games=games, today=today,
                           check_result=None, check_error=None, check_confirmation=None)
 
 
@app.route("/winning-numbers/check", methods=["POST"])
@login_required
def check_ticket():
    """
    POST: look up a confirmation number and tell the user
    whether their ticket is a winner.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    confirmation = request.form.get("confirmation_number", "").strip().upper()
    games = db.execute(
        "SELECT * FROM ticket_types WHERE is_active = 1 ORDER BY drawing_date ASC"
    ).fetchall()

    if not confirmation:
        return render_template("winning_numbers.html", games=games,
                               check_result=None, check_error="Please enter a confirmation number.",
                               check_confirmation=confirmation, today=today)

    row = db.execute("""
            SELECT t.confirmation_number, t.is_winner, t.claim_status,
                   t.match_count, t.winning_amount, tt.game_name
            FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE t.confirmation_number = ? AND o.user_id = ?
        """, (confirmation, session["user_id"])).fetchone()

    if row is None:
        return render_template("winning_numbers.html", games=games,
                               check_result=None,
                               check_error="No ticket found with that confirmation number.",
                               check_confirmation=confirmation, today=today)

    return render_template("winning_numbers.html", games=games,
                           check_result=row, check_error=None,
                           check_confirmation=confirmation, today=today)
 
 
@app.route("/admin/set-winning-numbers", methods=["POST"])
@login_required
@admin_required
def set_winning_numbers():
    """
    Admin-only POST: save winning numbers for a game and
    automatically flag matching tickets as winners.
    """
    db = get_db()
    ticket_type_id = int(request.form["ticket_type_id"])
    winning_numbers_raw = request.form["winning_numbers"].strip()

    try:
        winning_list = [str(int(n.strip())) for n in winning_numbers_raw.split(",")]
        winning_str = ",".join(winning_list)
    except ValueError:
        flash("Invalid format. Use comma-separated integers e.g. 4,17,23,38,45")
        return redirect(url_for("winning_numbers"))

    db.execute("UPDATE ticket_types SET winning_numbers = ? WHERE id = ?",
               (winning_str, ticket_type_id))

    game = db.execute("SELECT * FROM ticket_types WHERE id = ?", (ticket_type_id,)).fetchone()
    winning_set = set(winning_list)

    tickets = db.execute("""
            SELECT t.id, t.selected_numbers FROM tickets t
            WHERE t.ticket_type_id = ? AND t.result_status = 'pending_drawing'
        """, (ticket_type_id,)).fetchall()

    winner_count = 0
    for ticket in tickets:
        ticket_nums = set(n.strip() for n in ticket["selected_numbers"].split(","))
        match_count = len(ticket_nums & winning_set)
        prize = calc_prize(game["game_name"], match_count)
        is_winner = 1 if prize > 0 else 0
        result_status = "winning" if is_winner else "not_winning"
        if is_winner:
            winner_count += 1

        db.execute("""
                UPDATE tickets SET match_count=?, winning_amount=?, is_winner=?, result_status=?
                WHERE id=?
            """, (match_count, prize, is_winner, result_status, ticket["id"]))

    db.commit()
    flash(f"Winning numbers saved. {winner_count} winner(s) found.")
    return redirect(url_for("winning_numbers"))


@app.route("/search")
@login_required
def search():
    query = request.args.get("query", "").strip()
 
    tickets = []
 
    if query:
        db = get_db()
        tickets = db.execute("""
            SELECT t.*, tt.game_name, o.order_date
            FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE o.user_id = ?
              AND (tt.game_name LIKE ? OR t.confirmation_number LIKE ?)
            ORDER BY o.order_date DESC
        """, (session["user_id"], f"%{query}%", f"%{query}%")).fetchall()
 
    return render_template("search.html", tickets=tickets, query=query)

@app.route("/admin/finalize/<int:ticket_type_id>", methods=["POST"])
@login_required
@admin_required
def finalize_drawing(ticket_type_id):
    """
    Admin manually triggers the draw for a specific game.
    Generates winning numbers if not set, evaluates all tickets.
    Then schedules the next drawing to the following Sunday.
    """
    db = get_db()
    game = db.execute("SELECT * FROM ticket_types WHERE id = ?", (ticket_type_id,)).fetchone()

    # Use existing winning numbers or generate new ones
    if game["winning_numbers"]:
        winning_str = game["winning_numbers"]
        winning_set = set(n.strip() for n in winning_str.split(","))
    else:
        nums = sorted(random.sample(range(1, 51), 5))
        winning_str = ",".join(map(str, nums))
        winning_set = set(map(str, nums))
        db.execute("UPDATE ticket_types SET winning_numbers = ? WHERE id = ?",
                   (winning_str, ticket_type_id))

    # Evaluate pending tickets
    tickets = db.execute("""
        SELECT t.id, t.selected_numbers
        FROM tickets t
        WHERE t.ticket_type_id = ? AND t.result_status = 'pending_drawing'
    """, (ticket_type_id,)).fetchall()

    winner_count = 0
    for ticket in tickets:
        ticket_nums = set(n.strip() for n in ticket["selected_numbers"].split(","))
        match_count = len(ticket_nums & winning_set)
        prize = calc_prize(game["game_name"], match_count)
        is_winner = 1 if prize > 0 else 0
        result_status = "winning" if is_winner else "not_winning"
        if is_winner:
            winner_count += 1

        db.execute("""
            UPDATE tickets
            SET match_count = ?, winning_amount = ?, is_winner = ?, result_status = ?
            WHERE id = ?
        """, (match_count, prize, is_winner, result_status, ticket["id"]))

    # Schedule next drawing to next Sunday
    db.execute("UPDATE ticket_types SET drawing_date = ?, winning_numbers = NULL WHERE id = ?",
               (next_sunday(), ticket_type_id))

    db.commit()
    flash(f"Drawing finalized. Winning numbers: {winning_str}. {winner_count} winner(s).")
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)


