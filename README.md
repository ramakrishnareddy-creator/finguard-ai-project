# FinGuard AI — Semester Project

A dark-theme Python Flask + SQLite website for Financial Risk Analysis and Rule-Based Fraud Detection.

## Requirements
- Python 3.10+
- pip
- Internet for the Google Fonts import is optional; the app works without it.

## Run on Windows / VS Code
1. Extract `FinGuard_AI_Semester_Project.zip`.
2. Open the `finguard_ai` folder in VS Code.
3. Open Terminal and run:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python app.py
   ```
   If PowerShell blocks activation, run these directly:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe app.py
   ```
4. Visit `http://127.0.0.1:5000`.

The database and sample records are created automatically on the first run.

## Demo accounts
- User: `student` / `Student@123`
- Admin: `admin` / `Admin@123`

## Pages
Dashboard, Transaction Analyzer, Transaction History, Fraud Alerts, Financial Health, Risk Simulator.

Admin accounts can update a flagged case status. User accounts see their own transactions.

## Rule scoring
- Amount >= ₹50,000: +25
- Amount >= ₹20,000: +15
- Amount >= ₹10,000: +8
- Time from 11 PM through 4:59 AM: +15
- Location outside Hyderabad, Tirupati, Vijayawada, Chennai, Bengaluru: +20
- 2 recent transactions: +12; 3 or more: +25
- Cash withdrawal or international transfer: +10
- Score is capped at 100. Low = 0–29, Medium = 30–59, High = 60–100.

Rules are illustrative and should be calibrated for real data. A high risk score is not proof of fraud. The financial-health calculator is an educational heuristic, not financial advice.

## Important before deployment
Change `FINGUARD_SECRET_KEY`, change the demo passwords, disable debug mode, add CSRF protection and use HTTPS before deployment. Never enter real banking credentials or private financial records in this student demo.
