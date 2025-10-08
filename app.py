#!/usr/bin/env python3
"""
PayWave - single-file Flask app starter (Render-ready)
Admin: admin@paywave.com / admin123
"""
import os, time, sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, g, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.abspath(os.path.dirname(__file__))
DB = os.path.join(BASE, "paywave.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "paywave_dev_secret_change_me"
app.config['UPLOAD_FOLDER'] = UPLOADS
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(e=None):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        password TEXT,
        balance_ngn REAL DEFAULT 0,
        role TEXT DEFAULT 'user'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS rates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        method TEXT UNIQUE,
        rate_ngn_per_usd REAL,
        tag TEXT,
        status TEXT DEFAULT 'active'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        method TEXT,
        amount_usd REAL,
        amount_ngn REAL,
        proof TEXT,
        status TEXT,
        created_at REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        bank TEXT,
        account TEXT,
        amount_ngn REAL,
        status TEXT,
        created_at REAL
    )''')
    conn.commit()

    # default admin
    c.execute("SELECT id FROM users WHERE email=?", ("admin@paywave.com",))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (email,name,password,role,balance_ngn) VALUES (?,?,?,?,?)",
            ("admin@paywave.com", "PayWave Admin", generate_password_hash("admin123"), "admin", 0.0)
        )

    # default rates
    if c.execute("SELECT COUNT(*) FROM rates").fetchone()[0] == 0:
        defaults = [
            ("Bitcoin", 1300.0, "Send BTC to wallet: 1B72dozaVmjDAsEtFwJDhL96mqLcybmNyW", "active"),
            ("CashApp", 1100.0, "CashApp tag: $antoinephillip", "active"),
            ("Zelle", 1100.0, "Zelle to: rowancharle@gmail.com", "active"),
            ("PayPal", 1300.0, "PayPal: payments@paywave.com", "active"),
        ]
        c.executemany(
            "INSERT INTO rates (method, rate_ngn_per_usd, tag, status) VALUES (?, ?, ?, ?)", defaults
        )

    conn.commit()
    conn.close()

if not os.path.exists(DB):
    init_db()

# ---------- helpers ----------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

@app.context_processor
def inject_user():
    uid = session.get("user_id")
    if not uid:
        return dict(current_user=None, is_admin=False)
    db = get_db()
    row = db.execute("SELECT id,email,name,balance_ngn,role FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return dict(current_user=None, is_admin=False)
    return dict(current_user=row, is_admin=(row["role"] == "admin"))

# ---------- routes ----------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password required", "danger")
            return redirect(url_for("register"))
        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("Email already registered", "danger")
            return redirect(url_for("register"))
        db.execute(
            "INSERT INTO users (email,name,password,role,balance_ngn) VALUES (?,?,?,?,?)",
            (email, name or email, generate_password_hash(password), "user", 0.0)
        )
        db.commit()
        flash("Registration successful — please login", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            flash("Logged in", "success")
            return redirect(url_for("admin") if user["role"] == "admin" else url_for("dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- rest of routes remain same ----------
# (Dashboard, admin, trades, withdrawals, approvals, etc.)
# Everything below is same as your version — no need to retype if already correct.

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
