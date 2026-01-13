# Budget & Spending Analysis

Analyze personal spending from PDF bank/credit card statements.

## Deploy to Render.com (Free)

1. Upload these files to a new GitHub repository
2. Go to [render.com](https://render.com) → Sign up with GitHub
3. Click **New** → **Web Service** → Connect your repo
4. Render auto-detects settings → Click **Deploy**
5. Wait ~3 minutes, your app is live!

## Features

- Upload Chase, Amex, Truist PDF statements
- Auto-extract transactions
- View spending summary
- Filter by date and account

## Files

```
app.py          - Flask API
models.py       - Database models  
parsers.py      - PDF parsing logic
requirements.txt - Python dependencies
render.yaml     - Render deployment config
static/         - Pre-built frontend
uploads/        - Statement storage
```

## Supported Banks

- Chase (credit cards)
- American Express
- Truist (checking/savings)
- Generic PDF support for others
