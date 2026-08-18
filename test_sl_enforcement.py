#!/usr/bin/env python3
"""Test SL enforcement: verify 0.5% hard stop rule is detecting hits."""

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.intraday_session_engine import load_session
from app.services.exit_plan import evaluate_scale_trail_path

def test_godrejind_sl_hit():
    """Test GODREJIND: entry 1253.80, SL 1247.53, current 1197.50 — should hit."""
    session = load_session()
    
    # Find GODREJIND in session
    godrej = None
    for pos in (session.get("long") or []):
        if pos.get("symbol") == "GODREJIND":
            godrej = pos
            break
    
    if not godrej:
        print("❌ GODREJIND not found in locked intraday session")
        return False
    
    print(f"\n📊 GODREJIND Position:")
    print(f"   Entry: {godrej.get('entryPrice')}")
    print(f"   SL: {godrej.get('stopLoss')}")
    print(f"   Current (stale in JSON): {godrej.get('ltp')}")
    print(f"   Status in file: {godrej.get('status')}")
    
    # Test with LIVE price (1197.50)
    live_price = 1197.50
    print(f"\n   Live Market Price: {live_price}")
    print(f"   → Breach? {live_price} < {godrej.get('stopLoss')} = {live_price < godrej.get('stopLoss')}")
    
    # Simulate exit evaluation with live price
    test_pos = dict(godrej)
    test_pos["currentPrice"] = live_price
    test_pos["ltp"] = live_price
    
    result = evaluate_scale_trail_path(
        test_pos,
        live_price,
        day_high=godrej.get("sessionHigh") or live_price,
        day_low=godrej.get("sessionLow") or min(live_price, godrej.get("entryPrice", live_price)),
        after_close=False
    )
    
    if result:
        print(f"\n✅ EXIT EVALUATION RESULT:")
        print(f"   Label: {result.get('label')}")
        print(f"   Hit Level: {result.get('hitLevel')}")
        print(f"   Closed: {result.get('closed')}")
        print(f"   R Multiple: {result.get('rMultiple')}")
        
        if result.get("closed") and result.get("hitLevel") == "sl":
            print(f"\n🎯 SL RULE WORKING: Position should be marked CLOSED at {result.get('effectiveStop')}")
            return True
        else:
            print(f"\n⚠️  Exit detected but not SL: {result.get('label')}")
            return False
    else:
        print(f"\n❌ NO EXIT DETECTED — evaluation returned empty")
        return False


def test_pnb_sl_hit():
    """Test PNB: entry 118.37, SL 117.78, current 116.71 — should hit."""
    session = load_session()
    
    pnb = None
    for pos in (session.get("long") or []):
        if pos.get("symbol") == "PNB":
            pnb = pos
            break
    
    if not pnb:
        print("❌ PNB not found in locked intraday session")
        return False
    
    print(f"\n📊 PNB Position:")
    print(f"   Entry: {pnb.get('entryPrice')}")
    print(f"   SL: {pnb.get('stopLoss')}")
    print(f"   Current (stale in JSON): {pnb.get('ltp')}")
    
    live_price = 116.71
    print(f"\n   Live Market Price: {live_price}")
    print(f"   → Breach? {live_price} < {pnb.get('stopLoss')} = {live_price < pnb.get('stopLoss')}")
    
    test_pos = dict(pnb)
    test_pos["currentPrice"] = live_price
    test_pos["ltp"] = live_price
    
    result = evaluate_scale_trail_path(
        test_pos,
        live_price,
        day_high=pnb.get("sessionHigh") or live_price,
        day_low=pnb.get("sessionLow") or min(live_price, pnb.get("entryPrice", live_price)),
        after_close=False
    )
    
    if result:
        print(f"\n✅ EXIT EVALUATION RESULT:")
        print(f"   Label: {result.get('label')}")
        print(f"   Hit Level: {result.get('hitLevel')}")
        print(f"   Closed: {result.get('closed')}")
        
        if result.get("closed") and result.get("hitLevel") == "sl":
            print(f"\n🎯 SL RULE WORKING: Position should be marked CLOSED")
            return True
        else:
            print(f"\n⚠️  Exit detected but not SL: {result.get('label')}")
            return False
    else:
        print(f"\n❌ NO EXIT DETECTED — evaluation returned empty")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("TEST: 0.5% SL Hard Stop Rule Enforcement")
    print("=" * 70)
    
    r1 = test_godrejind_sl_hit()
    r2 = test_pnb_sl_hit()
    
    print("\n" + "=" * 70)
    if r1 and r2:
        print("✅ RESULT: SL Rule is working correctly in evaluation engine")
        print("   Issue: Session file not being updated with live prices")
        print("   Fix: Call /api/live-prices to refresh, or restart scheduler")
    else:
        print("❌ RESULT: SL Rule evaluation has issues")
    print("=" * 70)
