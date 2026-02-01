import os

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

# Détection Europe via suffixes (Yahoo-style)
EU_SUFFIXES = (".PA", ".AS", ".BR", ".DE", ".MI", ".MC", ".LS", ".SW", ".ST", ".OL", ".CO", ".HE", ".VI", ".IR")

def infer_market_from_symbol(sym: str) -> str:
    s = (sym or "").upper()
    return "EU" if s.endswith(EU_SUFFIXES) else "US"

# 11 secteurs GICS (codes stables + label FR)
GICS = {
    "Energy": {"label": "Énergie", "keywords": ["oil","brent","wti","opec","gas","lng","refining","drilling","pipeline","uranium"]},
    "Materials": {"label": "Matériaux", "keywords": ["mining","metals","copper","iron ore","steel","aluminum","lithium","nickel","chemicals","fertilizer","cement","paper","packaging"]},
    "Industrials": {"label": "Industrie", "keywords": ["aerospace","defense","aircraft","industrial","machinery","logistics","shipping","rail","construction","engineering","capex","contracts","nato"]},
    "Consumer Discretionary": {"label": "Conso discrétionnaire", "keywords": ["auto","ev","vehicle","consumer spending","travel","booking","hotel","airline","retail","e-commerce","luxury demand","cyclical"]},
    "Consumer Staples": {"label": "Conso de base", "keywords": ["grocery","food","beverage","household","staples","supermarket","tobacco","consumer defensive","pricing"]},
    "Health Care": {"label": "Santé", "keywords": ["pharma","biotech","clinical","trial","fda","drug","medicine","medical device","medtech","vaccine","hospital"]},
    "Financials": {"label": "Finance", "keywords": ["bank","banque","credit","loan","mortgage","insurance","assurance","asset management","broker","capital markets","m&a","merger","acquisition"]},
    "Information Technology": {"label": "Technologie", "keywords": ["semiconductor","chip","gpu","ai","ia","cloud","saas","software","cyber","data center","hardware","it spending","enterprise"]},
    "Communication Services": {"label": "Communication", "keywords": ["telecom","5g","broadband","media","streaming","advertising","social network","platform","gaming","content"]},
    "Utilities": {"label": "Services publics", "keywords": ["utility","electricity","power grid","water","regulated","tariff","transmission","distribution"]},
    "Real Estate": {"label": "Immobilier", "keywords": ["real estate","reit","property","office","residential","housing","commercial property","rent","mortgage rates"]},
}

# Thèmes transversaux (tags)
THEMES = {
    "Macro": ["inflation","cpi","pce","gdp","rates","taux","ecb","fed","fomc","yield","bonds","emploi","unemployment"],
    "Géopolitique": ["sanctions","tariffs","war","conflict","export ban","china","russia","middle east"],
    "Crypto": ["bitcoin","btc","ethereum","eth","crypto","sec crypto","bitcoin etf","spot etf"],
    "FX": ["eurusd","usd","dollar","yen","fx","forex","euro"],
    "Matières premières": ["gold","silver","copper","oil","brent","wti","natural gas","uranium"],
}

# Watchlist (boost du score + détection marché)
WATCHLIST = [
    # US
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","XOM",
    # EU
    "MC.PA","RMS.PA","AIR.PA","OR.PA","SAN.PA","BNP.PA","TTE.PA",
]