"""Service package bootstrap."""

# EOD forensic replay is diagnostic; the live Intraday execution ledger owns
# booked/partial/open economics. Install the narrow reconciliation wrapper once
# so every existing EOD call path (API, cache warmer, scheduler) sees one truth.
from .eod_intraday_authority import install as _install_intraday_eod_authority

_install_intraday_eod_authority()
del _install_intraday_eod_authority
