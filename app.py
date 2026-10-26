import os
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv
from datetime import datetime
from functools import wraps
from flask import Flask, g, render_template_string, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
app = Flask(__name__)
app.secret_key = os.environ.get("FINGUARD_SECRET_KEY", "replace-this-secret-before-deployment")


class PostgresConnection:
    """Small compatibility wrapper so the existing app can use PostgreSQL."""
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        self.raw = psycopg2.connect(url, cursor_factory=DictCursor, sslmode="require")

    def execute(self, sql, params=None):
        # Convert SQLite-style placeholders to PostgreSQL placeholders.
        sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.execute(sql, params or ())
        return cur

    def executemany(self, sql, rows):
        sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.executemany(sql, rows)
        return cur

    def executescript(self, script):
        cur = self.raw.cursor()
        for statement in script.split(";"):
            if statement.strip():
                cur.execute(statement)
        cur.close()

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing. Add it to your local .env file or Render environment variables.")
    if "db" not in g:
        g.db = PostgresConnection(DATABASE_URL)
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing. Set it before starting FinGuard AI.")
    db = PostgresConnection(DATABASE_URL)
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id SERIAL PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions(
          id SERIAL PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id),
          amount DOUBLE PRECISION NOT NULL,
          kind TEXT NOT NULL,
          location TEXT NOT NULL,
          merchant TEXT NOT NULL,
          tx_time TEXT NOT NULL,
          score INTEGER NOT NULL,
          level TEXT NOT NULL,
          reasons TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TIMESTAMP NOT NULL
        );
        """)
        for username, password, role in [("student", "Student@123", "user"), ("admin", "Admin@123", "admin")]:
            db.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?) ON CONFLICT(username) DO NOTHING",
                (username, generate_password_hash(password), role)
            )
        count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        if count == 0:
            uid = db.execute("SELECT id FROM users WHERE username='student'").fetchone()[0]
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            demo = [
                (uid, 1200, "Shopping", "Hyderabad", "Campus Store", "2026-10-22 10:15", 5, "Low", "No major rules triggered", "Cleared", now),
                (uid, 85000, "Transfer", "Unknown City", "QuickTransfer", "2026-10-22 02:10", 60, "High", "High amount; Unusual hour; Unfamiliar location", "Pending Review", now),
                (uid, 9500, "Online Payment", "Hyderabad", "ElectroHub", "2026-10-21 20:40", 8, "Low", "Amount above ₹10,000 threshold not reached", "Cleared", now),
                (uid, 25000, "Transfer", "Hyderabad", "RapidPay", "2026-10-20 23:55", 30, "Medium", "High amount; Late-night transaction", "Under Investigation", now),
            ]
            db.executemany("""INSERT INTO transactions(user_id,amount,kind,location,merchant,tx_time,score,level,reasons,status,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""", demo)
        db.commit()
    finally:
        db.close()


def assess(amount, kind, location, hour, frequency):
    score, reasons = 0, []
    if amount >= 50000:
        score += 25
        reasons.append("High transaction amount (₹50,000 or more)")
    elif amount >= 20000:
        score += 15
        reasons.append("Transaction amount above ₹20,000")
    elif amount >= 10000:
        score += 8
        reasons.append("Transaction amount above ₹10,000")

    if hour < 5 or hour >= 23:
        score += 15
        reasons.append("Unusual transaction hour (11 PM–5 AM)")

    usual = {"hyderabad", "tirupati", "vijayawada", "chennai", "bengaluru"}
    if location.strip().lower() not in usual:
        score += 20
        reasons.append("Location outside the configured usual-location list")

    if frequency >= 3:
        score += 25
        reasons.append("Frequent recent transactions")
    elif frequency == 2:
        score += 12
        reasons.append("Several recent transactions")

    if kind in {"Cash Withdrawal", "International Transfer"}:
        score += 10
        reasons.append("Higher-attention transaction type")

    score = min(score, 100)
    level = "High" if score >= 60 else "Medium" if score >= 30 else "Low"
    return score, level, reasons or ["No major rules triggered"]

def logged(view):
    @wraps(view)
    def inner(*a, **kw):
        if not session.get("uid"): return redirect(url_for("login"))
        return view(*a, **kw)
    return inner

def admin(view):
    @wraps(view)
    def inner(*a, **kw):
        if not session.get("uid"): return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Administrator access required.", "danger")
            return redirect(url_for("dashboard"))
        return view(*a, **kw)
    return inner

BASE = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title or 'FinGuard AI' }}</title><link rel="stylesheet" href="{{ url_for('static',filename='style.css') }}"></head><body>
{% if session.get('uid') %}<aside class="sidebar"><a class="brand" href="{{ url_for('dashboard') }}">⬡ <span>FinGuard <b>AI</b><small>FINANCIAL INTELLIGENCE</small></span></a>
<div class="navlabel">WORKSPACE</div>
<a href="{{ url_for('dashboard') }}">▦ Dashboard</a><a href="{{ url_for('analyzer') }}">⌕ Transaction Analyzer</a><a href="{{ url_for('transactions') }}">⇄ Transactions</a><a href="{{ url_for('alerts') }}">⚑ Fraud Alerts</a><a href="{{ url_for('health') }}">◉ Financial Health</a><a href="{{ url_for('simulator') }}">⌁ Risk Simulator</a>
<div class="userbox"><b>{{ session.get('username') }}</b><small>{{ session.get('role')|upper }}</small><a href="{{ url_for('logout') }}">Log out ↗</a></div></aside>{% endif %}
<main class="{{ 'with-sidebar' if session.get('uid') else '' }}"><header class="topbar"><span><i></i> Monitoring system <em> / Demo environment</em></span>{% if session.get('uid') %}<span class="secure">SECURE SESSION · {{ session.get('username') }}</span>{% endif %}</header>
<div class="wrap">{% with messages=get_flashed_messages(with_categories=true) %}{% for category,msg in messages %}<div class="flash {{ category }}">{{ msg }}</div>{% endfor %}{% endwith %}
{{ body|safe }}<footer>FinGuard AI · Educational demo only — not a real banking or fraud-confirmation service.</footer></div></main>
<script>document.querySelectorAll('.flash').forEach(x=>setTimeout(()=>x.remove(),5000));</script></body></html>
"""

def page(body, title="FinGuard AI", **context):
    return render_template_string(BASE, body=render_template_string(body, **context), title=title)

@app.route("/")
def home():
    if session.get("uid"): return redirect(url_for("dashboard"))
    body = r"""<section class="landing"><div class="eyebrow">RULE-BASED FINANCIAL MONITORING</div><h1>See risk before<br>it becomes <span>a threat.</span></h1>
    <p class="lead">A transparent financial risk and fraud detection workspace. Analyze transactions, understand risk signals and explore financial health — all in one place.</p>
    <p><a class="btn" href="{{ url_for('login') }}">Open workspace →</a></p><div class="featuregrid">
    <article><b>⌁ Transaction intelligence</b><p>Flag unusual amounts, late-night activity, unfamiliar locations and frequent transactions.</p></article>
    <article><b>◉ Financial health</b><p>Understand monthly balance, savings rate and debt pressure with a simple score.</p></article>
    <article><b>⚑ Explainable alerts</b><p>See the rules behind a score and track investigation status.</p></article></div>
    <div class="note">Demo user: <code>student / Student@123</code> &nbsp; · &nbsp; Admin: <code>admin / Admin@123</code></div></section>"""
    return page(body, "FinGuard AI | Home")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u=request.form.get("username","").strip()
        row=conn().execute("SELECT * FROM users WHERE username=?",(u,)).fetchone()
        if row and check_password_hash(row["password_hash"],request.form.get("password","")):
            session.clear(); session["uid"]=row["id"]; session["username"]=row["username"]; session["role"]=row["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.","danger")
    body=r"""<section class="login"><div class="eyebrow">WELCOME BACK</div><h1>Sign in to your<br><span>workspace.</span></h1><form method="post" class="form">
    <label>Username<input name="username" required autocomplete="username" placeholder="Enter username"></label>
    <label>Password<input type="password" name="password" required autocomplete="current-password" placeholder="Enter password"></label><button class="btn">Sign in →</button></form>
    <div class="note">User: <code>student / Student@123</code><br>Admin: <code>admin / Admin@123</code></div></section>"""
    return page(body,"Sign in | FinGuard AI")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/dashboard")
@logged
def dashboard():
    db=conn()
    if session["role"]=="admin":
        rows=db.execute("SELECT t.*,u.username FROM transactions t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC LIMIT 8").fetchall()
        scope="1=1"; args=()
    else:
        rows=db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 8",(session["uid"],)).fetchall()
        scope="user_id=?"; args=(session["uid"],)
    stats=db.execute(f"""SELECT COUNT(*) total,COALESCE(SUM(amount),0) value,
       SUM(CASE WHEN level='High' THEN 1 ELSE 0 END) high,
       SUM(CASE WHEN level='Medium' THEN 1 ELSE 0 END) medium,
       SUM(CASE WHEN status='Pending Review' THEN 1 ELSE 0 END) pending FROM transactions WHERE {scope}""",args).fetchone()
    body=r"""<div class="heading"><div><div class="eyebrow">OVERVIEW / MONITORING</div><h1>Good to see you, <span>{{ session.username }}.</span></h1><p>Here is your financial risk snapshot.</p></div><a class="btn" href="{{ url_for('analyzer') }}">＋ Analyze transaction</a></div>
    <div class="metrics"><div><small>Transactions analyzed</small><strong>{{ s.total or 0 }}</strong><em>Total recorded activity</em></div><div><small>Total transaction value</small><strong>₹{{ "{:,.0f}".format(s.value or 0) }}</strong><em>Across visible records</em></div><div><small>High-risk flags</small><strong>{{ s.high or 0 }}</strong><em class="red">Requires attention</em></div><div><small>Pending review</small><strong>{{ s.pending or 0 }}</strong><em>Awaiting a decision</em></div></div>
    <div class="columns"><section class="panel"><h2>Risk distribution</h2><p>Transactions grouped by detected risk level</p><div class="bars"><div><span>Low</span><b><i style="width:{{ (s.total-(s.high or 0)-(s.medium or 0))*100/(s.total or 1) }}%"></i></b></div><div><span>Medium</span><b><i class="orange" style="width:{{ (s.medium or 0)*100/(s.total or 1) }}%"></i></b></div><div><span>High</span><b><i class="redbar" style="width:{{ (s.high or 0)*100/(s.total or 1) }}%"></i></b></div></div><div class="note">Scores are screening signals, not proof of fraud.</div></section>
    <section class="panel"><h2>Quick actions</h2><p>Continue your risk analysis</p><a class="action" href="{{ url_for('alerts') }}">⚑ Review flagged activity →</a><a class="action" href="{{ url_for('health') }}">◉ Check financial health →</a><a class="action" href="{{ url_for('simulator') }}">⌁ Test a what-if scenario →</a></section></div>
    <section class="panel tablepanel"><div class="tablehead"><h2>Recent transactions</h2><a href="{{ url_for('transactions') }}">View all →</a></div><div class="scroll"><table><tr><th>TRANSACTION</th><th>AMOUNT</th><th>LOCATION</th><th>RISK</th><th>STATUS</th></tr>{% for t in rows %}<tr><td><b>{{ t.merchant }}</b><small>{{ t.kind }} · #{{ t.id }}</small></td><td>₹{{ "{:,.2f}".format(t.amount) }}</td><td>{{ t.location }}</td><td><span class="tag {{ t.level|lower }}">{{ t.level }} · {{ t.score }}</span></td><td>{{ t.status }}</td></tr>{% else %}<tr><td colspan="5">No transactions yet.</td></tr>{% endfor %}</table></div></section>"""
    return page(body,"Dashboard",s=stats,rows=rows)

@app.route("/analyzer", methods=["GET","POST"])
@logged
def analyzer():
    result=None
    if request.method=="POST":
        try:
            amount=float(request.form.get("amount","0"))
            if amount<=0 or amount>100000000: raise ValueError()
            kind=request.form.get("kind","Online Payment")
            location=request.form.get("location","Unknown").strip() or "Unknown"
            merchant=request.form.get("merchant","Unknown Merchant").strip() or "Unknown Merchant"
            raw=request.form.get("tx_time") or datetime.now().strftime("%Y-%m-%dT%H:%M")
            dt=datetime.strptime(raw,"%Y-%m-%dT%H:%M")
            freq=conn().execute("SELECT COUNT(*) FROM transactions WHERE user_id=? AND created_at >= NOW() - INTERVAL '1 day'",(session["uid"],)).fetchone()[0]
            score,level,reasons=assess(amount,kind,location,dt.hour,freq)
            status="Pending Review" if level!="Low" else "Cleared"
            cur=conn().execute("""INSERT INTO transactions(user_id,amount,kind,location,merchant,tx_time,score,level,reasons,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",(session["uid"],amount,kind,location,merchant,raw.replace("T"," "),score,level,"; ".join(reasons),status,datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            new_id = cur.fetchone()["id"]
            conn().commit(); result={"id":new_id,"amount":amount,"score":score,"level":level,"reasons":reasons,"status":status}
        except ValueError: flash("Enter a valid amount and date/time.","danger")
    body=r"""<div class="heading"><div><div class="eyebrow">RISK ENGINE / ANALYZER</div><h1>Analyze a <span>transaction.</span></h1><p>Assess fictional transaction details against configurable rules.</p></div></div>
    <div class="columns"><section class="panel"><h2>Transaction details</h2><p>Use sample or fictional data only.</p><form method="post" class="form">
    <label>Amount (INR)<input type="number" name="amount" min="1" step=".01" required placeholder="e.g. 25000"></label>
    <label>Transaction type<select name="kind">{% for x in ['Online Payment','Shopping','Transfer','Cash Withdrawal','International Transfer','Food'] %}<option>{{ x }}</option>{% endfor %}</select></label>
    <label>Location<input name="location" required value="Hyderabad"></label><label>Merchant / recipient<input name="merchant" required placeholder="e.g. Campus Store"></label>
    <label>Date and time<input type="datetime-local" id="tx_time" name="tx_time" required></label><button class="btn">Run risk assessment →</button></form></section>
    <section class="panel"><h2>Active detection rules</h2><div class="rule"><b>01 · High amount</b><p>₹10k / ₹20k / ₹50k thresholds · +8 to 25</p></div><div class="rule"><b>02 · Unusual hour</b><p>11 PM to 5 AM · +15</p></div><div class="rule"><b>03 · Location signal</b><p>Outside configured city list · +20</p></div><div class="rule"><b>04 · Recent frequency</b><p>Several recent transactions · +12 / 25</p></div><div class="rule"><b>05 · Transaction type</b><p>Cash withdrawal or international transfer · +10</p></div></section></div>
    {% if result %}<section class="panel result"><div class="tablehead"><div><div class="eyebrow">ASSESSMENT COMPLETE · #{{ result.id }}</div><h2>Risk assessment result</h2></div><span class="tag {{ result.level|lower }}">{{ result.level }} risk</span></div><div class="score"><strong>{{ result.score }}</strong><span>/ 100</span><div><h2>₹{{ "{:,.2f}".format(result.amount) }}</h2><p>Risk is based on the rules triggered.</p></div></div><h3>Why this score?</h3><ul>{% for r in result.reasons %}<li>{{ r }}</li>{% endfor %}</ul><p>Status: <b>{{ result.status }}</b></p><a class="btn secondary" href="{{ url_for('alerts') }}">View alerts →</a></section>{% endif %}"""
    response=page(body,"Transaction Analyzer",result=result)
    return response

def get_rows(alert_only=False):
    if session["role"]=="admin":
        sql="SELECT t.*,u.username FROM transactions t JOIN users u ON u.id=t.user_id"
        if alert_only: sql+=" WHERE t.level!='Low'"
        return conn().execute(sql+" ORDER BY t.id DESC").fetchall()
    sql="SELECT * FROM transactions WHERE user_id=?"
    if alert_only: sql+=" AND level!='Low'"
    return conn().execute(sql+" ORDER BY id DESC",(session["uid"],)).fetchall()

@app.route("/transactions")
@logged
def transactions():
    body=r"""<div class="heading"><div><div class="eyebrow">RECORDS / LEDGER</div><h1>Transaction <span>history.</span></h1><p>All transaction assessments visible to your account.</p></div><a class="btn" href="{{ url_for('analyzer') }}">＋ New assessment</a></div><section class="panel tablepanel"><div class="scroll"><table><tr><th>ID / MERCHANT</th>{% if session.role=='admin' %}<th>USER</th>{% endif %}<th>DATE</th><th>TYPE</th><th>AMOUNT</th><th>RISK</th><th>STATUS</th></tr>{% for t in rows %}<tr><td><b>#{{ t.id }} · {{ t.merchant }}</b><small>{{ t.location }}</small></td>{% if session.role=='admin' %}<td>{{ t.username }}</td>{% endif %}<td>{{ t.tx_time }}</td><td>{{ t.kind }}</td><td>₹{{ "{:,.2f}".format(t.amount) }}</td><td><span class="tag {{ t.level|lower }}">{{ t.level }} · {{ t.score }}</span></td><td>{{ t.status }}</td></tr>{% endfor %}</table></div></section>"""
    return page(body,"Transactions",rows=get_rows())

@app.route("/alerts")
@logged
def alerts():
    body=r"""<div class="heading"><div><div class="eyebrow">MONITORING / ALERT CENTER</div><h1>Suspicious <span>activity.</span></h1><p>Medium- and high-risk transactions need human review.</p></div></div><section class="panel tablepanel"><div class="scroll"><table><tr><th>TRANSACTION</th><th>AMOUNT</th><th>RISK</th><th>REASONS</th><th>STATUS</th>{% if session.role=='admin' %}<th>UPDATE CASE</th>{% endif %}</tr>{% for t in rows %}<tr><td><b>{{ t.merchant }}</b><small>#{{ t.id }} · {{ t.tx_time }}{% if t.username is defined %} · {{ t.username }}{% endif %}</small></td><td>₹{{ "{:,.2f}".format(t.amount) }}</td><td><span class="tag {{ t.level|lower }}">{{ t.level }} · {{ t.score }}</span></td><td class="reason">{{ t.reasons }}</td><td>{{ t.status }}</td>{% if session.role=='admin' %}<td><form method="post" action="{{ url_for('case',tid=t.id) }}" class="inline"><select name="status">{% for s in ['Pending Review','Under Investigation','Cleared','Confirmed Suspicious'] %}<option {{ 'selected' if t.status==s else '' }}>{{ s }}</option>{% endfor %}</select><button class="mini">Save</button></form></td>{% endif %}</tr>{% else %}<tr><td colspan="6">No alerts found.</td></tr>{% endfor %}</table></div></section>"""
    return page(body,"Fraud Alerts",rows=get_rows(True))

@app.route("/admin/case/<int:tid>",methods=["POST"])
@admin
def case(tid):
    status=request.form.get("status")
    allowed={"Pending Review","Under Investigation","Cleared","Confirmed Suspicious"}
    if status in allowed:
        conn().execute("UPDATE transactions SET status=? WHERE id=?",(status,tid)); conn().commit(); flash("Case status updated.","success")
    return redirect(url_for("alerts"))

@app.route("/financial-health",methods=["GET","POST"])
@logged
def health():
    result=None
    if request.method=="POST":
        try:
            income,expenses,debt,savings=[float(request.form.get(k,0)) for k in ("income","expenses","debt","savings")]
            if income<=0 or min(expenses,debt,savings)<0: raise ValueError()
            score=100
            if expenses>income: score-=35
            elif expenses>income*.8: score-=20
            if debt>income*6: score-=25
            elif debt>income*3: score-=12
            if savings<income: score-=10
            score=max(0,score)
            result={"score":score,"balance":income-expenses,"savings_rate":(income-expenses)/income*100,
                    "debt_ratio":debt/income*100,"label":"Healthy" if score>=75 else "Needs Attention" if score>=45 else "High Financial Pressure"}
        except ValueError: flash("Enter valid non-negative values and income greater than zero.","danger")
    body=r"""<div class="heading"><div><div class="eyebrow">ANALYTICS / FINANCIAL WELLNESS</div><h1>Understand your <span>financial health.</span></h1><p>Enter monthly amounts for an educational financial snapshot.</p></div></div><div class="columns"><section class="panel"><h2>Your financial snapshot</h2><form method="post" class="form">{% for name,label in [('income','Monthly income (₹)'),('expenses','Monthly expenses (₹)'),('debt','Total outstanding debt (₹)'),('savings','Current savings (₹)')] %}<label>{{ label }}<input type="number" name="{{ name }}" min="0" step=".01" required></label>{% endfor %}<button class="btn">Calculate financial health →</button></form></section><section class="panel"><h2>What is measured?</h2><div class="rule"><b>Monthly balance</b><p>Income minus expenses</p></div><div class="rule"><b>Savings rate</b><p>Share of income remaining after expenses</p></div><div class="rule"><b>Debt pressure</b><p>Debt compared with monthly income</p></div><p class="note">This is an educational heuristic, not a credit score or financial advice.</p></section></div>
    {% if result %}<section class="panel result"><div class="tablehead"><h2>{{ result.label }}</h2><span class="tag {{ 'low' if result.score>=75 else 'medium' if result.score>=45 else 'high' }}">{{ result.score }}/100</span></div><div class="metrics three"><div><small>MONTHLY BALANCE</small><strong>₹{{ "{:,.2f}".format(result.balance) }}</strong></div><div><small>SAVINGS RATE</small><strong>{{ "%.1f"|format(result.savings_rate) }}%</strong></div><div><small>DEBT / MONTHLY INCOME</small><strong>{{ "%.1f"|format(result.debt_ratio) }}%</strong></div></div></section>{% endif %}"""
    return page(body,"Financial Health",result=result)

@app.route("/simulator",methods=["GET","POST"])
@logged
def simulator():
    result=None
    if request.method=="POST":
        try:
            amount=float(request.form.get("amount",0)); freq=int(request.form.get("frequency",0)); hour=int(request.form.get("hour",12))
            if amount<=0 or not 0<=freq<=20 or not 0<=hour<=23: raise ValueError()
            score,level,reasons=assess(amount,request.form.get("kind","Online Payment"),request.form.get("location","Hyderabad"),hour,freq)
            result={"score":score,"level":level,"reasons":reasons}
        except ValueError: flash("Enter a valid amount, hour and frequency.","danger")
    body=r"""<div class="heading"><div><div class="eyebrow">LAB / WHAT-IF SIMULATOR</div><h1>Test a risk <span>scenario.</span></h1><p>Simulation only — no transaction is stored.</p></div></div><div class="columns"><section class="panel"><h2>Scenario builder</h2><form method="post" class="form"><label>Transaction amount (₹)<input type="number" name="amount" min="1" required placeholder="e.g. 75000"></label><label>Transaction type<select name="kind">{% for x in ['Online Payment','Transfer','Cash Withdrawal','International Transfer'] %}<option>{{ x }}</option>{% endfor %}</select></label><label>Location<input name="location" value="Hyderabad" required></label><label>Recent transactions<select name="frequency">{% for n in range(4) %}<option value="{{ n }}">{{ n }} recent transaction(s){{ ' or more' if n==3 else '' }}</option>{% endfor %}</select></label><label>Transaction hour<select name="hour">{% for h in range(24) %}<option value="{{ h }}" {{ 'selected' if h==12 else '' }}>{{ "%02d"|format(h) }}:00</option>{% endfor %}</select></label><button class="btn">Simulate risk →</button></form></section><section class="panel"><h2>Experiment ideas</h2><div class="rule"><b>Increase the amount</b><p>Compare ₹5,000 with ₹75,000.</p></div><div class="rule"><b>Change the hour</b><p>Compare noon with 02:00 AM.</p></div><div class="rule"><b>Change the location</b><p>Compare Hyderabad with an unfamiliar location.</p></div></section></div>
    {% if result %}<section class="panel result"><div class="tablehead"><h2>Predicted rule-based risk</h2><span class="tag {{ result.level|lower }}">{{ result.level }} risk</span></div><div class="score"><strong>{{ result.score }}</strong><span>/100</span></div><h3>Triggered rules</h3><ul>{% for r in result.reasons %}<li>{{ r }}</li>{% endfor %}</ul></section>{% endif %}"""
    return page(body,"Risk Simulator",result=result)

@app.route("/health-check")
def health_check(): return {"status":"ok","app":"FinGuard AI"}

 # Initialize PostgreSQL tables for both local runs and Render/Gunicorn startup.
init_db()

if __name__ == "__main__":
    app.run(debug=True)
