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
  searchType: "stock" | "index";
};

const INDEX_PLANS: Record<string, Omit<LookupPlan, "searchType">> = {
  NIFTY: { query: "NIFTY 50", expected: ["NIFTY"], exchange: "NSE" },
  NIFTY50: { query: "NIFTY 50", expected: ["NIFTY"], exchange: "NSE" },
  NIFTYBANK: { query: "NIFTY BANK", expected: ["BANKNIFTY"], exchange: "NSE" },
  BANKNIFTY: { query: "NIFTY BANK", expected: ["BANKNIFTY"], exchange: "NSE" },
  INDIAVIX: { query: "INDIA VIX", expected: ["INDIAVIX"], exchange: "NSE" },
  SENSEX: { query: "SENSEX", expected: ["SENSEX"], exchange: "BSE" },
  NIFTYIT: { query: "NIFTY IT", expected: ["CNXIT"], exchange: "NSE" },
  NIFTYPHARMA: { query: "NIFTY PHARMA", expected: ["CNXPHARMA"], exchange: "NSE" },
  NIFTYAUTO: { query: "NIFTY AUTO", expected: ["CNXAUTO"], exchange: "NSE" },
  NIFTYPSUBANK: { query: "NIFTY PSU BANK", expected: ["CNXPSUBANK"], exchange: "NSE" },
  NIFTYFINANCIALSERVICES: { query: "NIFTY FINANCIAL SERVICES", expected: ["CNXFINANCE"], exchange: "NSE" },
  NIFTYFMCG: { query: "NIFTY FMCG", expected: ["CNXFMCG"], exchange: "NSE" },
  NIFTYMEDIA: { query: "NIFTY MEDIA", expected: ["CNXMEDIA"], exchange: "NSE" },
  NIFTYMETAL: { query: "NIFTY METAL", expected: ["CNXMETAL"], exchange: "NSE" },
  NIFTYHEALTHCAREINDEX: { query: "NIFTY HEALTHCARE INDEX", expected: ["NIFTY_HEALTHCARE"], exchange: "NSE" },
  NIFTYREALTY: { query: "NIFTY REALTY", expected: ["CNXREALTY"], exchange: "NSE" },
  NIFTYENERGY: { query: "NIFTY ENERGY", expected: ["CNXENERGY"], exchange: "NSE" },
  NIFTYOILGAS: { query: "NIFTY OIL & GAS", expected: ["NIFTY_OIL_AND_GAS"], exchange: "NSE" },
  NIFTYCONSUMERDURABLES: { query: "NIFTY CONSUMER DURABLES", expected: ["NIFTY_CONSR_DURBL"], exchange: "NSE" },
  NIFTYMIDCAP100: { query: "NIFTY MIDCAP 100", expected: ["CNXMIDCAP"], exchange: "NSE" },
  NIFTYSMALLCAP100: { query: "NIFTY SMALLCAP 100", expected: ["CNXSMALLCAP"], exchange: "NSE" },
  NIFTY100: { query: "NIFTY 100", expected: ["CNX100"], exchange: "NSE" },
  DJIUS30: { query: "DOW JONES INDUSTRIAL AVERAGE", expected: ["DJI"], exchange: "DJ" },
  SP500: { query: "S&P 500", expected: ["SPX"], exchange: "SP" },
  NASDAQ100: { query: "NASDAQ 100", expected: ["NDX"], exchange: "NASDAQ" },
  NIKKEI225: { query: "NIKKEI 225", expected: ["NI225"], exchange: "TVC" },
  HANGSENG: { query: "HANG SENG", expected: ["HSI"], exchange: "HSI" },
  SHANGHAICOMP: { query: "SHANGHAI COMPOSITE", expected: ["SHCOMP", "000001"], exchange: "SSE" },
  DAX: { query: "DAX", expected: ["DAX"], exchange: "XETR" },
  CAC40: { query: "CAC 40", expected: ["PX1"], exchange: "Euronext Paris" },
  FTSE100: { query: "FTSE 100", expected: ["UKX"], exchange: "FTSE" },
  EUROSTOXX50: { query: "EURO STOXX 50", expected: ["SX5E"], exchange: "TVC" },
  SPASX200: { query: "XJO", expected: ["XJO"], exchange: "ASX" },
  BOVESPA: { query: "BOVESPA", expected: ["IBOV"], exchange: "BMFBOVESPA" },
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
    if (known) return { ...known, searchType: "index" };
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
    if (row.type && row.type !== plan.searchType) return false;
    if (plan.exchange && key(row.exchange || "") !== key(plan.exchange)) return false;
    return typeof row.symbol === "string" && expected.has(key(row.symbol));
  });
  const logoId = exact?.logo?.logoid || exact?.logoid;
  return typeof logoId === "string" && /^[a-z0-9][a-z0-9/_-]{0,159}$/i.test(logoId) ? logoId : null;
}
