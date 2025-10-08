#!/usr/bin/env python3
"""
PayWave - upgraded Flask app with admin totals and full admin routes
"""
import os
import time
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, g, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.abspath(os.path.dirname(__file__))
DB = os.path.join(BASE, "paywave.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("PAYWAVE_SECRET", "change_this_secret")
app.config['UPLOAD_FOLDER'] = UPLOADS
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB

# ---------- Database helpers ----------
import psycopg2
import urllib.parse as up

db_url = os.environ.get("DATABASE_URL")

if db_url:
    up.uses_netloc.append("postgres")
    url = up.urlparse(db_url)
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
else:
    import sqlite3
    conn = sqlite3.connect("paywave.db", check_same_thread=False)
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        password TEXT,
        balance_ngn REAL DEFAULT 0,
        role TEXT DEFAULT 'user'
    )''')
    # Rates table
    c.execute('''CREATE TABLE IF NOT EXISTS rates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        method TEXT UNIQUE,
        rate_ngn_per_usd REAL,
        tag TEXT,
        status TEXT DEFAULT 'active'
    )''')
    # Trades
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
    # Withdrawals
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
        c.execute("INSERT INTO users (email,name,password,role,balance_ngn) VALUES (?,?,?,?,?)",
                  ("admin@paywave.com", "PayWave Admin", generate_password_hash("admin123"), "admin", 0.0))
    # default rates
    defaults = [
        ("Bitcoin", 1400000.0, "Send BTC to wallet: 1PayBTCxyz", "active"),
        ("CashApp", 1400.0, "CashApp tag: $PayWaveCash", "active"),
        ("Zelle", 1400.0, "Zelle to: paywave@zellebank.com", "active"),
        ("PayPal", 1400.0, "PayPal: payments@paywave.com", "active"),
    ]
    for method, rate, tag, status in defaults:
        c.execute("INSERT OR IGNORE INTO rates (method,rate_ngn_per_usd,tag,status) VALUES (?,?,?,?)",
                  (method, rate, tag, status))
    conn.commit()
    conn.close()

if not os.path.exists(DB):
    init_db()

# ---------- Helpers ----------
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
    return dict(current_user=row, is_admin=(row["role"]=="admin"))

# ---------- Routes ----------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        name = request.form.get("name","").strip()
        password = request.form.get("password","")
        if not email or not password:
            flash("Email and password required", "danger")
            return redirect(url_for("register"))
        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("Email already registered", "danger")
            return redirect(url_for("register"))
        db.execute("INSERT INTO users (email,name,password,role,balance_ngn) VALUES (?,?,?,?,?)",
                   (email, name or email, generate_password_hash(password), "user", 0.0))
        db.commit()
        flash("Registration successful — please login", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            flash("Logged in", "success")
            return redirect(url_for("admin") if user["role"]=="admin" else url_for("dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    db = get_db()
    rates = db.execute("SELECT * FROM rates WHERE status IN ('active','locked')").fetchall()
    trades = db.execute("SELECT * FROM trades WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    withdrawals = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    user = db.execute("SELECT id,email,name,balance_ngn FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return render_template("dashboard.html", rates=rates, trades=trades, withdrawals=withdrawals, user=user)

@app.route("/rate_info/<method>")
def rate_info(method):
    db = get_db()
    r = db.execute("SELECT rate_ngn_per_usd, tag, status FROM rates WHERE method=?", (method,)).fetchone()
    if not r:
        return jsonify({"ok":False})
    return jsonify({"ok":True, "rate": r["rate_ngn_per_usd"], "tag": r["tag"], "status": r["status"]})

@app.route("/deposit", methods=["POST"])
def deposit():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    method = request.form.get("method")
    amount_usd = request.form.get("amount")
    try:
        amount_usd_f = float(amount_usd)
    except:
        flash("Enter a valid USD amount", "danger")
        return redirect(url_for("dashboard"))
    db = get_db()
    r = db.execute("SELECT rate_ngn_per_usd FROM rates WHERE method=?", (method,)).fetchone()
    if not r:
        flash("Invalid method", "danger")
        return redirect(url_for("dashboard"))
    amount_ngn = round(amount_usd_f * r["rate_ngn_per_usd"], 2)
    file = request.files.get("proof")
    filename = None
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("File type not allowed", "danger")
            return redirect(url_for("dashboard"))
        filename = secure_filename(f"{session['user_id']}_{int(time.time())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    db.execute("INSERT INTO trades (user_id,method,amount_usd,amount_ngn,proof,status,created_at) VALUES (?,?,?,?,?,?,?)",
               (session["user_id"], method, amount_usd_f, amount_ngn, filename, "Pending", time.time()))
    db.commit()
    flash("Trade submitted — status: Pending", "info")
    return redirect(url_for("dashboard"))

# ---------- Admin routes ----------
@app.route("/admin", methods=["GET","POST"])
def admin():
    if not session.get("user_id") or session.get("role") != "admin":
        return redirect(url_for("login"))

    db = get_db()
    users = db.execute("SELECT * FROM users").fetchall()
    trades = db.execute("SELECT t.*, u.email as user_email FROM trades t JOIN users u ON t.user_id=u.id ORDER BY t.created_at DESC").fetchall()
    withdrawals = db.execute("SELECT w.*, u.email as user_email FROM withdrawals w JOIN users u ON w.user_id=u.id ORDER BY w.created_at DESC").fetchall()
    rates = db.execute("SELECT * FROM rates").fetchall()

    # Handle rates update if POST
    if request.method == "POST":
        for r in rates:
            rate_val = request.form.get(f"rate_{r['id']}")
            tag_val = request.form.get(f"tag_{r['id']}")
            status_val = request.form.get(f"status_{r['id']}")
            db.execute("UPDATE rates SET rate_ngn_per_usd=?, tag=?, status=? WHERE id=?",
                       (rate_val, tag_val, status_val, r["id"]))
        db.commit()
        flash("Rates updated", "success")
        return redirect(url_for("admin"))

    totals = {
        "users": len(users),
        "trades": len(trades),
        "pending_trades": len([t for t in trades if t["status"]=="Pending"])
    }

    return render_template("admin.html", users=users, trades=trades, withdrawals=withdrawals, rates=rates, totals=totals)

# ---------- Approve / Reject routes ----------
@app.route("/approve_trade/<int:tid>")
def approve_trade(tid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    trade = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    if trade and trade["status"]=="Pending":
        db.execute("UPDATE trades SET status='Approved' WHERE id=?", (tid,))
        # update user balance
        db.execute("UPDATE users SET balance_ngn = balance_ngn + ? WHERE id=?", (trade["amount_ngn"], trade["user_id"]))
        db.commit()
        flash("Trade approved", "success")
    return redirect(url_for("admin"))

@app.route("/reject_trade/<int:tid>")
def reject_trade(tid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    trade = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    if trade and trade["status"]=="Pending":
        db.execute("UPDATE trades SET status='Rejected' WHERE id=?", (tid,))
        db.commit()
        flash("Trade rejected", "info")
    return redirect(url_for("admin"))

@app.route("/approve_withdraw/<int:wid>")
def approve_withdraw(wid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    w = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if w and w["status"]=="Pending":
        # subtract user balance
        db.execute("UPDATE users SET balance_ngn = balance_ngn - ? WHERE id=?", (w["amount_ngn"], w["user_id"]))
        db.execute("UPDATE withdrawals SET status='Approved' WHERE id=?", (wid,))
        db.commit()
        flash("Withdrawal approved", "success")
    return redirect(url_for("admin"))

@app.route("/reject_withdraw/<int:wid>")
def reject_withdraw(wid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    w = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if w and w["status"]=="Pending":
        db.execute("UPDATE withdrawals SET status='Rejected' WHERE id=?", (wid,))
        db.commit()
        flash("Withdrawal rejected", "info")
    return redirect(url_for("admin"))

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
