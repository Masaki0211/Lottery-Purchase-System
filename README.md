# Lottery Purchase System (LPS)

CS3365 group project — a Texas-lottery-style ticket purchasing website built with **Python / Flask** and **SQLite**.

Customers can register, buy tickets, check results and claim prizes. Admins manage the games, run the weekly drawings, verify claims and generate sales reports.

---

## ⚠️ Which folder is the real project?

The repo has **two copies of the app**. **`lottery-purchase-system-final/` is the real, finished project.** Use that one.

| Folder | What it is |
|--------|-----------|
| **`lottery-purchase-system-final/`** | ✅ **The final project.** All features, bug fixes and the latest UI. Use this one for running, grading and the demo. |
| `lottery-purchase-system/` | The earlier build we made **to show the course staff (TA / instructor) how the database gets initialized**. It's kept for reference only and is no longer updated. |

**Why two folders?**
During development we needed to show the course staff that the database could be built from `schema.sql` with one click (the **Initialize Database** link on the home page). We kept that version frozen as `lottery-purchase-system/` so it would stay stable for the demo. All later work continued in `lottery-purchase-system-final/`.

> The final project *also* still has the Initialize Database link, because you need it the first time you run the app. See [Removing the Initialize Database home page](#optional-removing-the-initialize-database-home-page) for how to hide it once setup is done.

---

## Requirements

- Python 3.9+
- Flask and Werkzeug (listed in `requirements.txt`)

## How to run

```bash
cd lottery-purchase-system-final
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

> On Windows, if `python` doesn't work, try `py app.py`.
> The old `lottery-purchase-system/` folder **must** be run from inside its own folder, because it opens `schema.sql` with a relative path. The final version works from any directory.

### First-time setup (initialize the database)

1. Open http://127.0.0.1:5000.
2. Click **Initialize Database** on the home page (or go to http://127.0.0.1:5000/init-db).
   - This **deletes all data** and rebuilds every table from `schema.sql`.
   - It also creates the 4 default games: Power Ball, Mega Millions, Lotto Texas and Texas Two Step. Each one draws on the coming Sunday.
3. Click **Register** and create an account. You must be 18 or older.

> ⚠️ Initializing wipes every account, including admin accounts. After initializing you need to register again and set up your admin account again.

---

## Admin accounts

### How to register as an admin

There is no "register as admin" button. Every new account is created as a regular `customer`. To make an account an admin:

1. Register a normal account on the website (for example, `you@ttu.edu`).
2. Stop the server (`Ctrl + C`) or leave it running. Either works.
3. In a terminal **inside `lottery-purchase-system-final/`** (where `database.db` lives), run:

   ```bash
   python
   ```
   ```python
   import sqlite3
   conn = sqlite3.connect("database.db")
   conn.execute("UPDATE users SET role='admin' WHERE email='you@ttu.edu'")
   conn.commit()
   conn.close()
   exit()
   ```

   Or as a single command:

   ```bash
   python -c "import sqlite3; c=sqlite3.connect('database.db'); c.execute(\"UPDATE users SET role='admin' WHERE email='you@ttu.edu'\"); c.commit()"
   ```

   Use your email in **lowercase**. The app saves emails in lowercase.

4. If you were already logged in, **log out and log back in**. Your role is read when you log in.

(The same steps are also in the `Admin Role` file.)

### How to log in as an admin

Admins use the **same Login page** as everyone else (http://127.0.0.1:5000/login). Log in with the email and password of the account you promoted.

After logging in as an admin:
- An **Admin** link shows up in the top menu, and **Admin Panel / Verify Ticket / View Reports** cards show up on the dashboard.
- Customer-only pages (Browse Tickets, Order History, Search) are hidden. Admins **cannot buy tickets**.
- Admin pages (`/admin/...`) send any non-admin back to the dashboard with "Admin access required."

To check who is an admin:
```bash
python -c "import sqlite3; print(sqlite3.connect('database.db').execute('SELECT email, role FROM users').fetchall())"
```

---

## Features

### Everyone
| Feature | Page |
|---------|------|
| Register (name, email, phone, address, date of birth, password). Blocks users under 18 and duplicate emails. | `/register` |
| Log in / log out | `/login`, `/logout` |
| **Profile page. View your account info and change your address** (customers and admins) | `/profile` |
| Winning numbers: current games and past drawing results | `/winning-numbers` |

### Customers
| Feature | Details |
|---------|---------|
| Dashboard | Quick links, plus an alert when you have unclaimed winning tickets |
| Browse tickets | Lists active games with price, prize and drawing date |
| Buy tickets | 1–10 tickets per order. **Auto pick** (random) or **manual pick** (5 unique numbers from 1–50, separated by commas) |
| Payment | Choose a payment method. Each ticket gets a 10-character **confirmation number** |
| Order history | All orders and tickets with their result status (pending / winning / non-winning) |
| Search | Search your tickets by game name or confirmation number |
| Check a ticket | Enter a confirmation number on the Winning Numbers page to see the result |
| Claim prizes | **$599 or less:** claim online through Venmo, PayPal or bank account. 24% tax is withheld. **Over $599:** you get a `CLAIM-XXXXXXXXXXXX` code to take to a claim center. The code is valid for 1 year after the drawing. |

### Admins
| Feature | Details |
|---------|---------|
| Admin panel | Shows active games and finished drawings |
| Add / edit / remove game | Change name, price, drawing date and prize. "Remove" hides the game from sale but keeps its history. |
| Finalize drawing | Only allowed on or after the drawing date. Generates winning numbers, scores every pending ticket and creates the next week's drawing automatically. |
| Verify ticket | Look up a ticket by claim code or confirmation number. Shows the customer, game, amount and claim status. |
| Sales report | Total revenue plus tickets sold and revenue per game. The report is saved, and the latest one is shown at `/admin/report`. |

### Prize rules
Every game: pick 5 numbers from 1–50. One drawing per week (Sunday).

| Matches | Prize |
|---------|-------|
| 5 | 100% of the jackpot |
| 4 | 20% |
| 3 | 5% |
| 2 | 1% |
| 0–1 | — |

---

## Project structure

```
Lottery-Purchase-System/
├── lottery-purchase-system-final/   ← the real project
│   ├── app.py              # Flask app: all routes and logic
│   ├── schema.sql          # Database tables (used by Initialize Database)
│   ├── database.db         # SQLite database
│   ├── requirements.txt
│   ├── static/style.css
│   └── templates/          # HTML pages (Jinja2)
├── lottery-purchase-system/         ← early build used to show DB initialization (reference only)
├── Admin Role                       # Notes: how to give an account admin role
├── Removing the home page with the initialize database   # Notes for the final demo
├── Phase 2 outline                  # Assignment description
└── class_diagram.pdf                # UML class diagram
```

### Database tables
`users`, `ticket_types` (games / drawings), `orders`, `tickets`, `payments`, `reports`. See `schema.sql`.

---

## (Optional) Removing the Initialize Database home page

After the final setup (initialize the database → register → make yourself admin), you can hide the Initialize Database page so nobody wipes the data by accident. For example, before recording the demo video:

1. In `app.py`, replace the `index()` route with:
   ```python
   @app.route("/")
   def index():
       if "user_id" in session:
           return redirect(url_for("dashboard"))
       return redirect(url_for("login"))
   ```
2. In `templates/base.html`, delete this line:
   ```html
   <a href="{{ url_for('index') }}">Home</a>
   ```

(The same steps are in the `Removing the home page with the initialize database` file.)
