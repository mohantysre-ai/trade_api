import test from "node:test";
import assert from "node:assert/strict";
import { buildLookupPlan } from "./symbol-logo.ts";

test("GIFT NIFTY resolves with correct logoId", () => {
  const plan = buildLookupPlan("GIFT NIFTY", "index");
  assert.equal(plan.logoId, "country/IN");
  assert.equal(plan.exchange, "NSEIX");
});

test("Commodities resolve with direct logoIds", () => {
  assert.equal(buildLookupPlan("SILVER", "index").logoId, "metal/silver");
  assert.equal(buildLookupPlan("BRENT CRUDE", "index").logoId, "crude-oil");
  assert.equal(buildLookupPlan("WTI CRUDE", "index").logoId, "crude-oil");
  assert.equal(buildLookupPlan("NATURAL GAS", "index").logoId, "natural-gas");
  assert.equal(buildLookupPlan("PLATINUM", "index").logoId, "metal/platinum");
  assert.equal(buildLookupPlan("PALLADIUM", "index").logoId, "metal/palladium");
  assert.equal(buildLookupPlan("GOLD", "index").logoId, "metal/gold");
  assert.equal(buildLookupPlan("COPPER", "index").logoId, "metal/copper");
  assert.equal(buildLookupPlan("WHEAT", "index").logoId, "commodity/wheat");
  assert.equal(buildLookupPlan("BITCOIN", "index").logoId, "crypto/XTVCBTC");
});

test("Forex USD / INR resolves with country/US logoId", () => {
  assert.equal(buildLookupPlan("USD / INR", "index").logoId, "country/US");
  assert.equal(buildLookupPlan("USD / INR SPOT", "index").logoId, "country/US");
});

test("Index plans resolve with direct logoIds", () => {
  assert.equal(buildLookupPlan("NIFTY MIDCAP", "index").logoId, "indices/nifty-midcap");
  assert.equal(buildLookupPlan("NIFTY SMALLCAP", "index").logoId, "indices/nifty-midcap");
  assert.equal(buildLookupPlan("CAC 40", "index").logoId, "indices/cac-40");
  assert.equal(buildLookupPlan("NASDAQ 100", "index").logoId, "indices/nasdaq-100");
  assert.equal(buildLookupPlan("DAX", "index").logoId, "indices/dax");
  assert.equal(buildLookupPlan("S&P 500", "index").logoId, "indices/s-and-p-500");
  assert.equal(buildLookupPlan("NIKKEI 225", "index").logoId, "indices/nikkei-225");
  assert.equal(buildLookupPlan("Sensex", "index").logoId, "indices/bse-sensex");
});
