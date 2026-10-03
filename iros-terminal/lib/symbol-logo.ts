export type LogoKind = "stock" | "index";

export type SearchResult = {
  symbol?: string;
  type?: string;
  exchange?: string;
  logoid?: string;
  logo?: { logoid?: string };
};

export type LookupPlan = {
  query: string;
  expected: string[];
  exchange?: string;
  searchType?: "stock" | "index";
  logoId?: string;
};

const INDEX_PLANS: Record<string, LookupPlan> = {
  NIFTY: { query: "NIFTY 50", expected: ["NIFTY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-50" },
  NIFTY50: { query: "NIFTY 50", expected: ["NIFTY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-50" },
  NIFTYBANK: { query: "NIFTY BANK", expected: ["BANKNIFTY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-bank-index" },
  BANKNIFTY: { query: "NIFTY BANK", expected: ["BANKNIFTY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-bank-index" },
  INDIAVIX: { query: "INDIA VIX", expected: ["INDIAVIX"], exchange: "NSE", searchType: "index", logoId: "indices/india-vix" },
  SENSEX: { query: "SENSEX", expected: ["SENSEX"], exchange: "BSE", searchType: "index", logoId: "indices/bse-sensex" },
  NIFTYIT: { query: "NIFTY IT", expected: ["CNXIT"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-it-index" },
  NIFTYPHARMA: { query: "NIFTY PHARMA", expected: ["CNXPHARMA"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-pharma-index" },
  NIFTYAUTO: { query: "NIFTY AUTO", expected: ["CNXAUTO"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-auto-index" },
  NIFTYPSUBANK: { query: "NIFTY PSU BANK", expected: ["CNXPSUBANK"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-bank-index" },
  NIFTYFINANCIALSERVICES: { query: "NIFTY FINANCIAL SERVICES", expected: ["CNXFINANCE"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-financial-services-index" },
  NIFTYFMCG: { query: "NIFTY FMCG", expected: ["CNXFMCG"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-noncyc-cons" },
  NIFTYMEDIA: { query: "NIFTY MEDIA", expected: ["CNXMEDIA"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-media-index" },
  NIFTYMETAL: { query: "NIFTY METAL", expected: ["CNXMETAL"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-metal-index" },
  NIFTYHEALTHCAREINDEX: { query: "NIFTY HEALTHCARE INDEX", expected: ["NIFTY_HEALTHCARE"], exchange: "NSE", searchType: "index" },
  NIFTYREALTY: { query: "NIFTY REALTY", expected: ["CNXREALTY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-housing" },
  NIFTYENERGY: { query: "NIFTY ENERGY", expected: ["CNXENERGY"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-energy-index" },
  NIFTYOILGAS: { query: "NIFTY OIL & GAS", expected: ["NIFTY_OIL_AND_GAS"], exchange: "NSE", searchType: "index" },
  NIFTYCONSUMERDURABLES: { query: "NIFTY CONSUMER DURABLES", expected: ["NIFTY_CONSR_DURBL"], exchange: "NSE", searchType: "index" },
  NIFTYMIDCAP: { query: "CNXMIDCAP", expected: ["CNXMIDCAP", "NIFTY_MID_SELECT"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-midcap" },
  NIFTYMIDCAP100: { query: "CNXMIDCAP", expected: ["CNXMIDCAP"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-midcap" },
  NIFTYSMALLCAP: { query: "CNXSMALLCAP", expected: ["CNXSMALLCAP"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-midcap" },
  NIFTYSMALLCAP100: { query: "CNXSMALLCAP", expected: ["CNXSMALLCAP"], exchange: "NSE", searchType: "index", logoId: "indices/nifty-midcap" },
  GIFTNIFTY: { query: "NIFTY", expected: ["NIFTY"], exchange: "NSEIX", logoId: "country/IN" },
  NIFTY100: { query: "NIFTY 100", expected: ["CNX100"], exchange: "NSE", searchType: "index", logoId: "indices/nifty100-enh-esg" },
  DJIUS30: { query: "DOW JONES INDUSTRIAL AVERAGE", expected: ["DJI"], exchange: "DJ", searchType: "index", logoId: "indices/dow-30" },
  SP500: { query: "S&P 500", expected: ["SPX"], exchange: "SP", searchType: "index", logoId: "indices/s-and-p-500" },
  NASDAQ100: { query: "NDX", expected: ["NDX", "US100", "NAS100"], exchange: "NASDAQ", searchType: "index", logoId: "indices/nasdaq-100" },
  NIKKEI225: { query: "NIKKEI 225", expected: ["NI225"], exchange: "TVC", searchType: "index", logoId: "indices/nikkei-225" },
  HANGSENG: { query: "HANG SENG", expected: ["HSI"], exchange: "HSI", searchType: "index", logoId: "indices/hang-seng" },
  SHANGHAICOMP: { query: "SHANGHAI COMPOSITE", expected: ["SHCOMP", "000001"], exchange: "SSE", searchType: "index", logoId: "indices/sse-composite" },
  DAX: { query: "DAX", expected: ["DAX"], exchange: "XETR", searchType: "index", logoId: "indices/dax" },
  CAC40: { query: "CAC40", expected: ["CAC40", "PX1"], exchange: "TVC", searchType: "index", logoId: "indices/cac-40" },
  FTSE100: { query: "FTSE 100", expected: ["UKX"], exchange: "FTSE", searchType: "index", logoId: "indices/uk-100" },
  EUROSTOXX50: { query: "EURO STOXX 50", expected: ["SX5E"], exchange: "TVC", searchType: "index", logoId: "indices/euro-stoxx-50" },
  SPASX200: { query: "XJO", expected: ["XJO"], exchange: "ASX", searchType: "index" },
  BOVESPA: { query: "BOVESPA", expected: ["IBOV"], exchange: "BMFBOVESPA", searchType: "index", logoId: "indices/bovespa-index" },
  TSX: { query: "TSX", expected: ["TSX"], exchange: "TSX", searchType: "index", logoId: "indices/s-and-p-tsx-composite-index" },
  KOSPI: { query: "KOSPI", expected: ["KOSPI"], exchange: "KRX", searchType: "index", logoId: "indices/korea-composite-index" },
  USDINR: { query: "USDINR", expected: ["USDINR"], logoId: "country/US" },
  USDINRSPOT: { query: "USDINR", expected: ["USDINR"], logoId: "country/US" },
  SILVER: { query: "SILVER", expected: ["SILVER"], exchange: "TVC", logoId: "metal/silver" },
  BRENTCRUDE: { query: "UKOIL", expected: ["UKOIL"], exchange: "TVC", logoId: "crude-oil" },
  BRENTCRUDEOIL: { query: "UKOIL", expected: ["UKOIL"], exchange: "TVC", logoId: "crude-oil" },
  WTICRUDE: { query: "USOIL", expected: ["USOIL"], exchange: "TVC", logoId: "crude-oil" },
  NATURALGAS: { query: "NG", expected: ["NG"], exchange: "NYMEX", logoId: "natural-gas" },
  PLATINUM: { query: "PLATINUM", expected: ["PLATINUM"], exchange: "TVC", logoId: "metal/platinum" },
  PALLADIUM: { query: "PALLADIUM", expected: ["PALLADIUM"], exchange: "TVC", logoId: "metal/palladium" },
  GOLD: { query: "GOLD", expected: ["GOLD"], logoId: "metal/gold" },
  COPPER: { query: "COPPER", expected: ["COPPER"], logoId: "metal/copper" },
  WHEAT: { query: "WHEAT", expected: ["WHEAT"], logoId: "commodity/wheat" },
  BITCOIN: { query: "BTCUSD", expected: ["BTCUSD", "BTC"], logoId: "crypto/XTVCBTC" },
  ALUMINUM: { query: "ALUMINUM", expected: ["ALUMINUM"], logoId: "metal/aluminum" },
  ZINC: { query: "ZINC", expected: ["ZINC"], logoId: "metal/zinc" },
  NICKEL: { query: "NICKEL", expected: ["NICKEL"], logoId: "metal/nickel" },
};

function decodeProviderText(value: string): string {
  return value
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/gi, "&")
    .replace(/&#38;/g, "&")
    .replace(/&nbsp;/gi, " ");
}

function key(value: string): string {
  return decodeProviderText(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function parseExchangeSymbol(raw: string): { symbol: string; exchange?: string } {
  const trimmed = raw.trim().toUpperCase();
  if (trimmed.includes(":")) {
    const [exchange, ...parts] = trimmed.split(":");
    return { exchange, symbol: parts.join(":") };
  }
  if (trimmed.endsWith(".NS")) return { exchange: "NSE", symbol: trimmed.slice(0, -3) };
  if (trimmed.endsWith(".BO")) return { exchange: "BSE", symbol: trimmed.slice(0, -3) };
  return { symbol: trimmed };
}

export function buildLookupPlan(rawSymbol: string, kind: LogoKind, defaultExchange = "NSE"): LookupPlan {
  const parsed = parseExchangeSymbol(rawSymbol);
  if (kind === "index") {
    const known = INDEX_PLANS[key(parsed.symbol)];
    if (known) return { ...known };
    return {
      query: parsed.symbol,
      expected: [key(parsed.symbol)],
      exchange: parsed.exchange,
      searchType: "index",
    };
  }
  return {
    query: parsed.symbol,
    expected: [key(parsed.symbol)],
    exchange: parsed.exchange || defaultExchange,
    searchType: "stock",
  };
}

export function selectExactLogo(results: SearchResult[], plan: LookupPlan): string | null {
  const expected = new Set(plan.expected.map(key));
  const exact = results.find((row) => {
    if (plan.exchange && key(row.exchange || "") !== key(plan.exchange)) return false;
    return typeof row.symbol === "string" && expected.has(key(row.symbol));
  });
  const logoId = exact?.logo?.logoid || exact?.logoid;
  return typeof logoId === "string" && /^[a-z0-9][a-z0-9/_-]{0,159}$/i.test(logoId) ? logoId : null;
}
