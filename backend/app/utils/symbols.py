"""IROS watchlist and macro instruments for Angel One SmartAPI.

The backend now treats the stock universe as one live collection that is
ranked dynamically by the filter prompt and LLM selection step.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    key: str
    exchange: str
    tradingsymbol: str
    token: str
    label: str | None = None


# Live universe used by Angel One data ingestion.
WATCHLIST: list[Instrument] = [
    Instrument("RELIANCE", "NSE", "RELIANCE-EQ", "2885"),
    Instrument("TCS", "NSE", "TCS-EQ", "11536"),
    Instrument("INFY", "NSE", "INFY-EQ", "1594"),
    Instrument("HDFCBANK", "NSE", "HDFCBANK-EQ", "1333"),
    Instrument("ICICIBANK", "NSE", "ICICIBANK-EQ", "4963"),
    Instrument("KOTAKBANK", "NSE", "KOTAKBANK-EQ", "1922"),
    Instrument("SBIN", "NSE", "SBIN-EQ", "3045"),
    Instrument("LT", "NSE", "LT-EQ", "11483"),
    Instrument("HCLTECH", "NSE", "HCLTECH-EQ", "7229"),
    Instrument("ITC", "NSE", "ITC-EQ", "1660"),
    Instrument("WIPRO", "NSE", "WIPRO-EQ", "3787"),
    Instrument("AXISBANK", "NSE", "AXISBANK-EQ", "5900"),
    Instrument("BHARTIARTL", "NSE", "BHARTIARTL-EQ", "10604"),
    Instrument("HINDUNILVR", "NSE", "HINDUNILVR-EQ", "1394"),
    Instrument("MARUTI", "NSE", "MARUTI-EQ", "10999"),
    Instrument("BAJFINANCE", "NSE", "BAJFINANCE-EQ", "317"),
    Instrument("TITAN", "NSE", "TITAN-EQ", "3506"),
    Instrument("BAJAJFINSV", "NSE", "BAJAJFINSV-EQ", "16675"),
    Instrument("NESTLEIND", "NSE", "NESTLEIND-EQ", "17963"),
    Instrument("SUNPHARMA", "NSE", "SUNPHARMA-EQ", "3351"),
    Instrument("HAL", "NSE", "HAL-EQ", "2303"),
    Instrument("BEL", "NSE", "BEL-EQ", "383"),
    Instrument("IRFC", "NSE", "IRFC-EQ", "2029"),
    Instrument("MAZDOCK", "NSE", "MAZDOCK-EQ", "509"),
    Instrument("BHEL", "NSE", "BHEL-EQ", "438"),
    Instrument("POWERGRID", "NSE", "POWERGRID-EQ", "14977"),
    Instrument("NTPC", "NSE", "NTPC-EQ", "11630"),
    Instrument("ONGC", "NSE", "ONGC-EQ", "2475"),
    Instrument("COALINDIA", "NSE", "COALINDIA-EQ", "20374"),
    Instrument("DRREDDY", "NSE", "DRREDDY-EQ", "881"),
    Instrument("CIPLA", "NSE", "CIPLA-EQ", "694"),
    Instrument("GODREJPROP", "NSE", "GODREJPROP-EQ", "17875"),
    Instrument("ASIANPAINT", "NSE", "ASIANPAINT-EQ", "236"),
    Instrument("ULTRACEMCO", "NSE", "ULTRACEMCO-EQ", "11532"),
    Instrument("TECHM", "NSE", "TECHM-EQ", "13538"),
    Instrument("DIXON", "NSE", "DIXON-EQ", "21690"),
    Instrument("KAYNES", "NSE", "KAYNES-EQ", "12092"),
    Instrument("DATAPATTNS", "NSE", "DATAPATTNS-EQ", "7358"),
    Instrument("TATAELXSI", "NSE", "TATAELXSI-EQ", "3411"),
    Instrument("COFORGE", "NSE", "COFORGE-EQ", "11543"),
    Instrument("MPHASIS", "NSE", "MPHASIS-EQ", "4503"),
    Instrument("PERSISTENT", "NSE", "PERSISTENT-EQ", "18365"),
    Instrument("VOLTAS", "NSE", "VOLTAS-EQ", "3718"),
    Instrument("PIIND", "NSE", "PIIND-EQ", "24184"),
    Instrument("DEEPAKNTR", "NSE", "DEEPAKNTR-EQ", "19943"),
    Instrument("APLAPOLLO", "NSE", "APLAPOLLO-EQ", "25780"),
    Instrument("ABCAPITAL", "NSE", "ABCAPITAL-EQ", "21614"),
    Instrument("KPITTECH", "NSE", "KPITTECH-EQ", "9683"),
    Instrument("TEGA", "NSE", "TEGA-EQ", "7105"),
    Instrument("NETWEB", "NSE", "NETWEB-EQ", "17433"),
    Instrument("RAILTEL", "NSE", "RAILTEL-EQ", "2431"),
    Instrument("ALKYLAMINE", "NSE", "ALKYLAMINE-EQ", "4487"),
    Instrument("EXICOM", "NSE", "EXICOM-EQ", "22947"),
    Instrument("ROUTE", "NSE", "ROUTE-EQ", "128"),
    Instrument("SYRMA", "NSE", "SYRMA-EQ", "10793"),
    Instrument("JYOTHYLAB", "NSE", "JYOTHYLAB-EQ", "15146"),
    Instrument("DPWIRES", "NSE", "DPWIRES-EQ", "16900"),
    Instrument("KSOLVES", "NSE", "KSOLVES-EQ", "11060"),
    Instrument("SMCGLOBAL", "NSE", "SMCGLOBAL-EQ", "2320"),
    Instrument("HAPPYFORGE", "NSE", "HAPPYFORGE-EQ", "20854"),
    Instrument("WESTLIFE", "NSE", "WESTLIFE-EQ", "11580"),
    Instrument("ZENTEC", "NSE", "ZENTEC-EQ", "7508"),
    Instrument("SAPPHIRE", "NSE", "SAPPHIRE-EQ", "6718"),
]

MOCK_TICKERS: set[str] = {"AWFI"}

# Macro strip instruments (NSE/BSE indices).
MACRO_INSTRUMENTS: list[Instrument] = [
    Instrument("nifty50", "NSE", "Nifty 50", "99926000", "Nifty 50"),
    Instrument("sensex", "BSE", "SENSEX", "99919000", "Sensex"),
    Instrument("banknifty", "NSE", "Nifty Bank", "99926009", "Nifty Bank"),
]
