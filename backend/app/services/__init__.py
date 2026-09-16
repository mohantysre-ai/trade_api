"""Service package bootstrap."""

# EOD forensic replay is diagnostic; the live Intraday execution ledger owns
# booked/partial/open economics. Install the narrow reconciliation wrapper once
# so every existing EOD call path (API, cache warmer, scheduler) sees one truth.
from .eod_intraday_authority import install as _install_intraday_eod_authority

_install_intraday_eod_authority()
del _install_intraday_eod_authority

# Final persistence boundary: project all locked session rows after close/force,
# overlay exact execution economics, then persist that same object to Book cache
# and master EOD. This prevents a correct live response with a stale EOD cache.
from .eod_intraday_parity import install as _install_intraday_eod_parity

_install_intraday_eod_parity()
del _install_intraday_eod_parity

# Index Options V2 keeps deterministic scoring/construction, but makes the
# in-memory Angel stream + durable paper ledger authoritative at execution time.
# BUY and defined-risk SELL use independent correlation/governor sleeves while
# still sharing the global max-open and seller risk caps.
from .index_options_live_authority import install as _install_index_options_live_authority

_install_index_options_live_authority()
del _install_index_options_live_authority
