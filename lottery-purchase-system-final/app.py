import os
import sqlite3
import random
import string
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-to-something-random"


PRIZE_PERCENTAGES = {
    5: 1.00,
    4: 0.20,
    3: 0.05,
    2: 0.01,
    1: 0.00,
    0: 0.00,
}

DEFAULT_GAMES = [
    {"game_name": "Power Ball", "price": 2.00, "prize_amount": 1000000.00},
    {"game_name": "Mega Millions", "price": 2.00, "prize_amount": 2000000.00},
    {"game_name": "Lotto Texas", "price": 1.00, "prize_amount": 500000.00},
    {"game_name": "Texas Two Step", "price": 1.50, "prize_amount": 250000.00},
]


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


def get_target_sunday(base_date):
    base = datetime.strptime(base_date, "%Y-%m-%d")
    days_until_sunday = 6 - base.weekday()
    return (base + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")


def next_drawing_date(base_date):
    base = datetime.strptime(base_date, "%Y-%m-%d")
    return (base + timedelta(days=7)).strftime("%Y-%m-%d")


def ensure_default_games():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    first_sunday = get_target_sunday(today)

    for game in DEFAULT_GAMES:
        existing = db.execute(
            "SELECT COUNT(*) AS count FROM ticket_types WHERE game_name = ? AND is_active = 1",
            (game["game_name"],)
        ).fetchone()["count"]

        if existing == 0:
            db.execute("""
                INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
                VALUES (?, ?, ?, ?, NULL, 1)
            """, (
                game["game_name"],
                game["price"],
                first_sunday,
                game["prize_amount"]
            ))

    db.commit()


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


def generate_numbers(mode="auto", manual_pick=None):
    if mode == "auto":
        nums = sorted(random.sample(range(1, 51), 5))
        return ",".join(map(str, nums))
    return manual_pick


def generate_confirmation():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def generate_claim_code():
    return "CLAIM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def parse_number_string(number_string):
    try:
        nums = [int(n.strip()) for n in number_string.split(",")]
    except (ValueError, AttributeError):
        return None

    if len(nums) != 5:
        return None

    if len(set(nums)) != 5:
        return None

    if any(n < 1 or n > 50 for n in nums):
        return None

    return sorted(nums)


def validate_lotto_numbers(raw):
    nums = parse_number_string(raw)
    if nums is None:
        return None
    return ",".join(map(str, nums))


def calculate_winnings(selected_numbers, winning_numbers, prize_amount):
    selected = parse_number_string(selected_numbers)
    winning = parse_number_string(winning_numbers)

    if selected is None or winning is None:
        return 0, 0, 0.0

    match_count = len(set(selected) & set(winning))
    percent = PRIZE_PERCENTAGES.get(match_count, 0.0)
    winning_amount = round(float(prize_amount) * percent, 2)
    is_winner = 1 if winning_amount > 0 else 0

    return match_count, is_winner, winning_amount


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
        confirm_password = request.form.get("confirm_password", password)
        dob = request.form.get("dob")

        if not name or not email or not phone or not address or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        if dob:
            try:
                birth_date = datetime.strptime(dob, "%Y-%m-%d")
                today = datetime.today()
                age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

                if age < 18:
                    flash("You must be 18 years old or older to register.")
                    return redirect(url_for("register"))
            except ValueError:
                flash("Invalid date of birth.")
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
            INSERT INTO users (name, email, phone, address, password_hash, role, dob)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email, phone, address, password_hash, "customer", dob))

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


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()

    winning_count = db.execute("""
        SELECT COUNT(*) AS count
        FROM tickets t
        JOIN orders o ON t.order_id = o.id
        WHERE o.user_id = ?
        AND t.result_status = 'winning'
        AND t.claim_status = 'not_claimed'
    """, (session["user_id"],)).fetchone()["count"]

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name"),
        winning_count=winning_count
    )


@app.route("/profile")
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
    if session.get("role") == "admin":
        flash("Admins cannot access ticket purchasing.")
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    tickets = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 1
        ORDER BY game_name, drawing_date
    """).fetchall()
    return render_template("tickets.html", tickets=tickets)


@app.route("/purchase/<int:ticket_type_id>", methods=["GET", "POST"])
@login_required
def purchase(ticket_type_id):
    if session.get("role") == "admin":
        flash("Admins are not allowed to purchase tickets.")
        return redirect(url_for("admin_dashboard"))
    
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

        numbers_list = []

        if selection_mode == "auto":
            for _ in range(quantity):
                numbers_list.append(generate_numbers("auto"))
        else:
            for i in range(quantity):
                raw = (
                    request.form.get(f"manual_numbers_{i}", "").strip()
                    or request.form.get("manual_numbers", "").strip()
                )

                cleaned_numbers = validate_lotto_numbers(raw)

                if cleaned_numbers is None:
                    flash(f"Ticket {i + 1}: enter 5 unique numbers between 1 and 50, separated by commas.")
                    return redirect(url_for("purchase", ticket_type_id=ticket_type_id))

                numbers_list.append(cleaned_numbers)

        session["pending_order"] = {
            "ticket_type_id": ticket_type_id,
            "game_name": ticket_type["game_name"],
            "quantity": quantity,
            "selection_mode": selection_mode,
            "total_amount": ticket_type["price"] * quantity,
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
                (
                    order_id,
                    ticket_type_id,
                    selected_numbers,
                    selection_mode,
                    confirmation_number,
                    is_winner,
                    match_count,
                    winning_amount,
                    result_status,
                    claim_status,
                    payout_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                order["ticket_type_id"],
                numbers,
                order["selection_mode"],
                generate_confirmation(),
                0,
                0,
                0.0,
                "pending_drawing",
                "not_claimed",
                "none"
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
        flash("Purchase successful! Ticket results will be available after the drawing.")
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
        SELECT t.*, tt.game_name, tt.prize_amount, tt.drawing_date
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE o.user_id = ?
        ORDER BY o.order_date DESC, t.id DESC
    """, (session["user_id"],)).fetchall()

    return render_template("orders.html", orders=orders, tickets=tickets)


@app.route("/winning-numbers")
def winning_numbers():
    db = get_db()

    active_games = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 1
        ORDER BY drawing_date ASC
    """).fetchall()

    past_games = db.execute("""
        SELECT *
        FROM ticket_types
        WHERE is_active = 0
        AND winning_numbers IS NOT NULL
        ORDER BY drawing_date DESC
    """).fetchall()

    return render_template(
        "winning_numbers.html",
        active_games=active_games,
        past_games=past_games,
        games=active_games,
        check_result=None,
        check_error=None,
        check_confirmation=None
    )


@app.route("/winning-numbers/check", methods=["POST"])
@login_required
def check_ticket():
    db = get_db()
    confirmation = request.form.get("confirmation_number", "").strip().upper()

    active_games = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 1
        ORDER BY drawing_date ASC
    """).fetchall()

    past_games = db.execute("""
        SELECT *
        FROM ticket_types
        WHERE is_active = 0
        AND winning_numbers IS NOT NULL
        ORDER BY drawing_date DESC
    """).fetchall()

    if not confirmation:
        return render_template(
            "winning_numbers.html",
            active_games=active_games,
            past_games=past_games,
            games=active_games,
            check_result=None,
            check_error="Please enter a confirmation number.",
            check_confirmation=confirmation
        )

    row = db.execute("""
        SELECT t.confirmation_number,
               t.is_winner,
               t.claim_status,
               t.result_status,
               t.match_count,
               t.winning_amount,
               tt.game_name
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE t.confirmation_number = ?
        AND o.user_id = ?
    """, (confirmation, session["user_id"])).fetchone()

    if row is None:
        return render_template(
            "winning_numbers.html",
            active_games=active_games,
            past_games=past_games,
            games=active_games,
            check_result=None,
            check_error="No ticket found with that confirmation number on your account.",
            check_confirmation=confirmation
        )

    return render_template(
        "winning_numbers.html",
        active_games=active_games,
        past_games=past_games,
        games=active_games,
        check_result=row,
        check_error=None,
        check_confirmation=confirmation
    )


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


@app.route("/claim/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def claim_ticket(ticket_id):
    db = get_db()

    ticket = db.execute("""
        SELECT t.*, tt.game_name, tt.prize_amount, tt.drawing_date, o.user_id
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        JOIN orders o ON t.order_id = o.id
        WHERE t.id = ?
    """, (ticket_id,)).fetchone()

    if ticket is None:
        flash("Ticket not found.")
        return redirect(url_for("orders"))

    if ticket["user_id"] != session["user_id"]:
        flash("You do not have permission to claim this ticket.")
        return redirect(url_for("orders"))

    if ticket["result_status"] != "winning" or ticket["is_winner"] != 1:
        flash("Only winning tickets can be claimed.")
        return redirect(url_for("orders"))

    if ticket["claim_status"] == "claimed":
        flash("This ticket has already been claimed.")
        return redirect(url_for("orders"))

    if ticket["winning_amount"] <= 599:
        if request.method == "POST":
            payout_method = request.form.get("payout_method") or request.form.get("payment_method")

            if payout_method not in ["Venmo", "PayPal", "Bank Account"]:
                flash("Please select a valid payout method.")
                return redirect(url_for("claim_ticket", ticket_id=ticket_id))

            tax_withheld = round(ticket["winning_amount"] * 0.24, 2)
            net_amount = round(ticket["winning_amount"] - tax_withheld, 2)

            db.execute("""
                UPDATE tickets
                SET claim_status = ?,
                    claim_method = ?,
                    claim_date = ?,
                    payout_type = ?,
                    tax_withheld = ?,
                    net_payout = ?
                WHERE id = ?
            """, (
                "claimed",
                payout_method,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "small",
                tax_withheld,
                net_amount,
                ticket_id
            ))
            db.commit()

            flash(f"Prize claimed successfully. ${net_amount:.2f} sent through {payout_method}.")
            return redirect(url_for("orders"))

        return render_template("claim.html", ticket=ticket, claim_type="online")

    claim_code = ticket["claim_code"]

    if not claim_code:
        claim_code = generate_claim_code()
        db.execute("""
            UPDATE tickets
            SET claim_code = ?,
                claim_method = ?,
                payout_type = ?
            WHERE id = ?
        """, (
            claim_code,
            "Claim Center",
            "large",
            ticket_id
        ))
        db.commit()

        ticket = db.execute("""
            SELECT t.*, tt.game_name, tt.prize_amount, tt.drawing_date, o.user_id
            FROM tickets t
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            JOIN orders o ON t.order_id = o.id
            WHERE t.id = ?
        """, (ticket_id,)).fetchone()

    drawing_date = datetime.strptime(ticket["drawing_date"], "%Y-%m-%d")
    exp_date = (drawing_date + timedelta(days=365)).strftime("%Y-%m-%d")

    return render_template("claim.html", ticket=ticket, claim_type="center", exp_date=exp_date)


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    tickets = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 1
        ORDER BY game_name, drawing_date
    """).fetchall()

    completed_tickets = db.execute("""
        SELECT * FROM ticket_types
        WHERE is_active = 0
        AND winning_numbers IS NOT NULL
        ORDER BY drawing_date DESC
    """).fetchall()

    return render_template("admin.html", tickets=tickets, completed_tickets=completed_tickets)


@app.route("/admin/verify-ticket", methods=["GET", "POST"])
@login_required
@admin_required
def verify_ticket():
    result = None

    if request.method == "POST":
        code = request.form.get("verify_code", "").strip()

        db = get_db()
        result = db.execute("""
            SELECT t.*, u.name AS user_name, tt.game_name, tt.drawing_date, tt.prize_amount
            FROM tickets t
            JOIN orders o ON t.order_id = o.id
            JOIN users u ON o.user_id = u.id
            JOIN ticket_types tt ON t.ticket_type_id = tt.id
            WHERE t.claim_code = ? OR t.confirmation_number = ?
        """, (code, code)).fetchone()

    return render_template("admin_verify.html", result=result)


@app.route("/admin/add", methods=["GET", "POST"])
@app.route("/admin/ticket/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_ticket():
    if request.method == "POST":
        game_name = request.form["game_name"].strip()
        price = float(request.form["price"])
        drawing_date = request.form["drawing_date"]
        prize_amount = float(request.form["prize_amount"])

        db = get_db()
        db.execute("""
            INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
            VALUES (?, ?, ?, ?, NULL, 1)
        """, (game_name, price, drawing_date, prize_amount))
        db.commit()

        flash("Ticket type added.")
        return redirect(url_for("admin_dashboard"))

    game_names = [g["game_name"] for g in DEFAULT_GAMES]
    return render_template("add_ticket.html", game_names=game_names)

@app.route("/admin/edit/<int:ticket_id>", methods=["GET", "POST"])
@app.route("/admin/ticket/edit/<int:ticket_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_ticket(ticket_id):
    db = get_db()
    ticket = db.execute("SELECT * FROM ticket_types WHERE id = ?", (ticket_id,)).fetchone()

    if ticket is None:
        flash("Ticket not found.")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        game_name = request.form.get("game_name", ticket["game_name"]).strip()
        price = float(request.form["price"])
        drawing_date = request.form["drawing_date"]
        prize_amount = float(request.form["prize_amount"])
        active = int(request.form["is_active"])

        db.execute("""
            UPDATE ticket_types
            SET game_name = ?,
                price = ?,
                drawing_date = ?,
                prize_amount = ?,
                is_active = ?
            WHERE id = ?
        """, (
            game_name,
            price,
            drawing_date,
            prize_amount,
            active,
            ticket_id
        ))
        db.commit()

        flash("Ticket updated.")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_ticket.html", ticket=ticket)


@app.route("/admin/delete/<int:ticket_id>", methods=["POST"])
@app.route("/admin/ticket/delete/<int:ticket_id>", methods=["POST"])
@login_required
@admin_required
def delete_ticket(ticket_id):
    db = get_db()
    db.execute("UPDATE ticket_types SET is_active = 0 WHERE id = ?", (ticket_id,))
    db.commit()
    flash("Ticket removed from active listings.")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/finalize/<int:ticket_type_id>", methods=["POST"])
@login_required
@admin_required
def finalize_drawing(ticket_type_id):
    db = get_db()

    game = db.execute(
        "SELECT * FROM ticket_types WHERE id = ?",
        (ticket_type_id,)
    ).fetchone()

    if game is None:
        flash("Ticket type not found.")
        return redirect(url_for("admin_dashboard"))

    today = datetime.now().date()
    drawing_date = datetime.strptime(game["drawing_date"], "%Y-%m-%d").date()

    if today < drawing_date:
        flash("This drawing cannot be finalized before the drawing date.")
        return redirect(url_for("admin_dashboard"))

    winning_numbers = generate_numbers()

    db.execute(
        "UPDATE ticket_types SET winning_numbers = ? WHERE id = ?",
        (winning_numbers, ticket_type_id)
    )

    pending_tickets = db.execute("""
        SELECT *
        FROM tickets
        WHERE ticket_type_id = ?
        AND result_status = 'pending_drawing'
    """, (ticket_type_id,)).fetchall()

    winner_count = 0

    for ticket in pending_tickets:
        match_count, is_winner, winning_amount = calculate_winnings(
            ticket["selected_numbers"],
            winning_numbers,
            game["prize_amount"]
        )

        result_status = "winning" if is_winner else "non_winning"
        payout_type = "small" if 0 < winning_amount <= 599 else ("large" if winning_amount > 599 else "none")

        db.execute("""
            UPDATE tickets
            SET match_count = ?,
                winning_amount = ?,
                is_winner = ?,
                result_status = ?,
                payout_type = ?
            WHERE id = ?
        """, (
            match_count,
            winning_amount,
            is_winner,
            result_status,
            payout_type,
            ticket["id"]
        ))

        if is_winner:
            winner_count += 1

    db.execute("""
        INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
        VALUES (?, ?, ?, ?, NULL, 1)
    """, (
        game["game_name"],
        game["price"],
        next_drawing_date(game["drawing_date"]),
        game["prize_amount"]
    ))

    db.execute("UPDATE ticket_types SET is_active = 0 WHERE id = ?", (ticket_type_id,))
    db.commit()

    flash(f"Drawing finalized. Winning numbers: {winning_numbers}. {winner_count} winner(s).")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/generate-report", methods=["POST"])
@login_required
@admin_required
def generate_report():
    db = get_db()

    total_revenue = db.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM payments
        WHERE payment_status = 'approved'
    """).fetchone()["total"]

    ticket_sales = db.execute("""
        SELECT tt.game_name,
               tt.price,
               COUNT(t.id) AS tickets_sold,
               COUNT(t.id) * tt.price AS game_revenue
        FROM tickets t
        JOIN ticket_types tt ON t.ticket_type_id = tt.id
        GROUP BY tt.game_name, tt.price
        ORDER BY tickets_sold DESC
    """).fetchall()

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
        "SELECT name FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()["name"]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db.execute("""
        INSERT INTO reports (generated_by, generated_at, total_revenue, report_data)
        VALUES (?, ?, ?, ?)
    """, (
        admin_name,
        generated_at,
        total_revenue,
        json.dumps(sales_data)
    ))
    db.commit()

    flash("Report generated successfully.")
    return redirect(url_for("view_report"))


@app.route("/admin/report")
@login_required
@admin_required
def view_report():
    db = get_db()

    report = db.execute(
        "SELECT * FROM reports ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if report is None:
        return render_template("report.html", report=None)

    sales_data = json.loads(report["report_data"])
    return render_template("report.html", report=report, sales_data=sales_data)


if __name__ == "__main__":
    app.run(debug=True)
