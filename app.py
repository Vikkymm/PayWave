#!/usr/bin/env python3
"""
PayWave - single-file Flask app starter (cleaned)
Keep your existing DB; this file expects paywave.db in the same folder.
Admin: admin@paywave.com / admin123
"""
import os
import time
import sqlite3
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, g, jsonify
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.abspath(os.path.dirname(__file__))
DB = os.path.join(BASE, "paywave.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "paywave_dev_secret_change_me"  # change in production
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
    defaults = [
        ("Bitcoin", 1400000.0, "Send BTC to wallet: 1PayBTCxyz", "active"),
        ("CashApp", 1400.0, "CashApp tag: $PayWaveCash", "active"),
        ("Zelle", 1400.0, "Zelle to: paywave@zellebank.com", "active"),
        ("PayPal", 1400.0, "PayPal: payments@paywave.com", "active"),
    ]
    for method, rate, tag, status in defaults:
        c.execute(
            "INSERT OR IGNORE INTO rates (method,rate_ngn_per_usd,tag,status) VALUES (?,?,?,?)",
            (method, rate, tag, status)
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
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# register
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

# login
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

# logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# dashboard
@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    db = get_db()
    rates = db.execute("SELECT * FROM rates WHERE status='active' OR status='locked'").fetchall()
    trades = db.execute("SELECT * FROM trades WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    withdrawals = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    user = db.execute("SELECT id,email,name,balance_ngn FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return render_template("dashboard.html", rates=rates, trades=trades, withdrawals=withdrawals, user=user)

# AJAX: get rate & tag for method (used in modal)
@app.route("/rate_info/<method>")
def rate_info(method):
    db = get_db()
    r = db.execute("SELECT rate_ngn_per_usd, tag, status FROM rates WHERE method=?", (method,)).fetchone()
    if not r:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "rate": r["rate_ngn_per_usd"], "tag": r["tag"], "status": r["status"]})

# deposit (trade)
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

    db.execute(
        "INSERT INTO trades (user_id,method,amount_usd,amount_ngn,proof,status,created_at) VALUES (?,?,?,?,?,?,?)",
        (session["user_id"], method, amount_usd_f, amount_ngn, filename, "Pending", time.time())
    )
    db.commit()
    flash("Trade submitted — status: Pending", "info")
    return redirect(url_for("dashboard"))

# withdraw
@app.route("/withdraw", methods=["POST"])
def withdraw():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    name = request.form.get("name", "").strip()
    bank = request.form.get("bank", "").strip()
    account = request.form.get("account", "").strip()
    amount_ngn = request.form.get("amount")
    try:
        amount_ngn_f = float(amount_ngn)
    except:
        flash("Enter valid amount", "danger")
        return redirect(url_for("dashboard"))
    if not all([name, bank, account]):
        flash("Fill all withdrawal fields", "danger")
        return redirect(url_for("dashboard"))

    db = get_db()
    user = db.execute("SELECT balance_ngn FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user:
        flash("User not found", "danger")
        return redirect(url_for("login"))

    # IMPORTANT: only allow withdraw request if user has sufficient balance
    if amount_ngn_f > user["balance_ngn"]:
        flash("Insufficient balance for this withdrawal.", "danger")
        return redirect(url_for("dashboard"))

    db.execute(
        "INSERT INTO withdrawals (user_id,name,bank,account,amount_ngn,status,created_at) VALUES (?,?,?,?,?,?,?)",
        (session["user_id"], name, bank, account, amount_ngn_f, "Pending", time.time())
    )
    db.commit()
    flash("Withdrawal requested — Pending", "info")
    return redirect(url_for("dashboard"))

# admin
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if session.get("role") != "admin":
        flash("Admin access required", "danger")
        return redirect(url_for("login"))
    db = get_db()
    if request.method == "POST":
        # update rates and tags/status
        rates = db.execute("SELECT * FROM rates").fetchall()
        for r in rates:
            rid = r["id"]
            new_rate = request.form.get(f"rate_{rid}")
            new_tag = request.form.get(f"tag_{rid}")
            new_status = request.form.get(f"status_{rid}")
            if new_rate:
                try:
                    db.execute("UPDATE rates SET rate_ngn_per_usd=? WHERE id=?", (float(new_rate), rid))
                except:
                    pass
            if new_tag is not None:
                db.execute("UPDATE rates SET tag=? WHERE id=?", (new_tag, rid))
            if new_status in ("active", "locked"):
                db.execute("UPDATE rates SET status=? WHERE id=?", (new_status, rid))
        db.commit()
        flash("Rates & tags updated", "success")
        return redirect(url_for("admin"))

    users = db.execute("SELECT * FROM users").fetchall()
    rates = db.execute("SELECT * FROM rates").fetchall()
    trades = db.execute(
        "SELECT t.*, u.email as user_email FROM trades t JOIN users u ON u.id=t.user_id ORDER BY t.created_at DESC"
    ).fetchall()
    withdrawals = db.execute(
        "SELECT w.*, u.email as user_email FROM withdrawals w JOIN users u ON u.id = w.user_id ORDER BY w.created_at DESC"
    ).fetchall()
    totals = {
        "users": db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"],
        "trades": db.execute("SELECT COUNT(*) as c FROM trades").fetchone()["c"],
        "pending_trades": db.execute("SELECT COUNT(*) as c FROM trades WHERE status='Pending'").fetchone()["c"],
        "pending_withdrawals": db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='Pending'").fetchone()["c"],
    }
    return render_template("admin.html", users=users, rates=rates, trades=trades, withdrawals=withdrawals, totals=totals)

# approve/reject trade
@app.route("/approve_trade/<int:tid>")
def approve_trade(tid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    t = db.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    if t and t["status"] == "Pending":
        db.execute("UPDATE trades SET status='Approved' WHERE id=?", (tid,))
        db.execute("UPDATE users SET balance_ngn = balance_ngn + ? WHERE id=?", (t["amount_ngn"], t["user_id"]))
        db.commit()
        flash("Trade approved and user credited", "success")
    return redirect(url_for("admin"))

@app.route("/reject_trade/<int:tid>")
def reject_trade(tid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    db.execute("UPDATE trades SET status='Rejected' WHERE id=?", (tid,))
    db.commit()
    flash("Trade rejected", "warning")
    return redirect(url_for("admin"))

# approve/reject withdraw
@app.route("/approve_withdraw/<int:wid>")
def approve_withdraw(wid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    w = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if w and w["status"] == "Pending":
        user = db.execute("SELECT balance_ngn FROM users WHERE id=?", (w["user_id"],)).fetchone()
        if user and user["balance_ngn"] >= w["amount_ngn"]:
            db.execute("UPDATE withdrawals SET status='Approved' WHERE id=?", (wid,))
            db.execute("UPDATE users SET balance_ngn = balance_ngn - ? WHERE id=?", (w["amount_ngn"], w["user_id"]))
            db.commit()
            flash("Withdrawal approved and balance updated", "success")
        else:
            db.execute("UPDATE withdrawals SET status='Rejected' WHERE id=?", (wid,))
            db.commit()
            flash("Cannot approve - user has insufficient balance. Withdrawal rejected.", "warning")
    return redirect(url_for("admin"))

@app.route("/reject_withdraw/<int:wid>")
def reject_withdraw(wid):
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    db = get_db()
    db.execute("UPDATE withdrawals SET status='Rejected' WHERE id=?", (wid,))
    db.commit()
    flash("Withdrawal rejected", "warning")
    return redirect(url_for("admin"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
