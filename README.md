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
