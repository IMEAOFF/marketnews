# Market News Dashboard

A lightweight **Flask** dashboard to track **market-moving news** (US / Europe / Unknown), saved **by day**, categorized by **sectors (GICS-style)** and themes, with filters and optional **EN → FR** translation per article.

> UI is **English by default** and can be switched to **French** using the 🌐 button.  
> News content is not auto-translated (you choose per article).

---

## Features

- **Daily snapshots** saved locally (SQLite) — browse what happened **yesterday / any day**
- **US / Europe / Unknown** split
- **Sector classification** (GICS-style) + **themes tags**
- Filters: **date**, **sector**, **min score**, **search**, **sort**
- API key manager:
  - add keys
  - switch active key
  - estimate daily usage (NewsAPI)
- Optional translation per news card:
  - **title + summary**
  - **full article** (may fail on paywalled / blocked sites)

---

## Tech Stack

- Python + Flask
- SQLite (`news.db`)
- News sources:
  - **NewsAPI** (Everything endpoint)
  - **Finnhub** (general market news)
- Optional translation: **Argos Translate** (offline)

---

## Setup (macOS / Linux)

```bash
cd news-dashboard

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python app.py


Open in your browser:
	•	http://127.0.0.1:5000

⸻

API Keys

You need at least one provider:
	•	NewsAPI: https://newsapi.org/register
	•	Finnhub: https://finnhub.io/register

Keys are managed from the UI (“API Keys” section).
They are stored locally in the database (news.db, table api_keys).

Local Data & Privacy

All data is stored locally:
	•	news.db contains snapshots, articles, translations, and API keys.
	•	The database file is ignored by git and should not be committed.

⸻

Notes
	•	Some websites block full-article fetching (403/401/paywalls).
In that case, use title + summary translation instead.
	•	NewsAPI has rate limits depending on your plan. The app tracks requests approximately.

Project Structure
.
├── app.py
├── config.py
├── requirements.txt
├── static/
│   └── app.css
└── templates/
    ├── layout.html
    └── index.html

License

MIT
MD
