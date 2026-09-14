"""Register all index-options strategies."""

from __future__ import annotations

from .bear_call_credit import BearCallCreditSpread
from .bear_put_debit import BearPutDebitSpread
from .bull_call_debit import BullCallDebitSpread
from .bull_put_credit import BullPutCreditSpread
from .call_calendar import CallCalendarStrategy
from .call_diagonal import CallDiagonalStrategy
from .iron_butterfly import IronButterflyStrategy
from .iron_condor import IronCondorStrategy
from .long_call import LongCallStrategy
from .long_call_butterfly import LongCallButterflyStrategy
from .long_put import LongPutStrategy
from .long_put_butterfly import LongPutButterflyStrategy
from .long_straddle import LongStraddleStrategy
from .long_strangle import LongStrangleStrategy
from .put_calendar import PutCalendarStrategy
from .put_diagonal import PutDiagonalStrategy
from ..strategy_registry import register_strategy

register_strategy(LongCallStrategy())
register_strategy(LongPutStrategy())
register_strategy(BullPutCreditSpread())
register_strategy(BearCallCreditSpread())
register_strategy(IronCondorStrategy())
register_strategy(BullCallDebitSpread())
register_strategy(BearPutDebitSpread())
register_strategy(LongStraddleStrategy())
register_strategy(LongStrangleStrategy())
register_strategy(IronButterflyStrategy())
register_strategy(LongCallButterflyStrategy())
register_strategy(LongPutButterflyStrategy())
register_strategy(CallCalendarStrategy())
register_strategy(PutCalendarStrategy())
register_strategy(CallDiagonalStrategy())
register_strategy(PutDiagonalStrategy())
