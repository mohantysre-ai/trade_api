"""Service package bootstrap."""

# EOD forensic replay is diagnostic; the live Intraday execution ledger owns
# booked/partial/open economics. Install the narrow reconciliation wrapper once
# so every existing EOD call path (API, cache warmer, scheduler) sees one truth.
from .eod_intraday_authority import install as _install_intraday_eod_authority

_install_intraday_eod_authority()
del _install_intraday_eod_authority

# Index Options V2 keeps deterministic scoring/construction, but makes the
# in-memory Angel stream + durable paper ledger authoritative at execution time.
# BUY and defined-risk SELL use independent correlation/governor sleeves while
# still sharing the global max-open and seller risk caps.
from .index_options_live_authority import install as _install_index_options_live_authority

_install_index_options_live_authority()
del _install_index_options_live_authority
