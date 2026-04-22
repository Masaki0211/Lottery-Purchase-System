import os
import sqlite3
import random
import string
from datetime import datetime
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


def seed_ticket_types():
    db = get_db()
    existing = db.execute("SELECT COUNT(*) AS count FROM ticket_types").fetchone()["count"]

    if existing == 0:
        sample_tickets = [
            ("Power Ball", 2.00, "2026-05-01", 1000000.00, None, 1),
            ("Mega Millions", 2.00, "2026-05-03", 2000000.00, None, 1),
            ("Lotto Texas", 1.00, "2026-05-05", 500000.00, None, 1),
            ("Texas Two Step", 1.50, "2026-05-07", 250000.00, None, 1),
        ]

        db.executemany("""
            INSERT INTO ticket_types
            (game_name, price, drawing_date, prize_amount, winning_numbers, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sample_tickets)
        db.commit()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


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
    return render_template("dashboard.html", user_name=session.get("user_name"))


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



        total_amount = ticket_type["price"] * quantity

        manual_picks = []
        if selection_mode == "manual":
            raw = request.form.get("manual_numbers", "").strip()
            if not raw:
                flash("Please enter numbers")
                return redirect(url_for("purchase", ticket_type_id=ticket_type_id))
            manual_picks = [raw] * quantity

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

        db = get_db()
        db.execute("""
            INSERT INTO ticket_types (game_name, price, drawing_date, prize_amount, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (name, price, date, prize))
        db.commit()

        flash("Ticket added!")
        return redirect(url_for("admin_dashboard"))

    return render_template("add_ticket.html")

@app.route("/admin/edit/<int:ticket_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_ticket(ticket_id):
    db = get_db()

    ticket = db.execute(
        "SELECT * FROM ticket_types WHERE id = ?",
        (ticket_id,)
    ).fetchone()

    if request.method == "POST":
        name = request.form["game_name"]
        price = float(request.form["price"])
        date = request.form["drawing_date"]
        prize = float(request.form["prize_amount"])
        active = int(request.form["is_active"])

        db.execute("""
            UPDATE ticket_types
            SET game_name=?, price=?, drawing_date=?, prize_amount=?, is_active=?
            WHERE id=?
        """, (name, price, date, prize, active, ticket_id))

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



if __name__ == "__main__":
    app.run(debug=True)