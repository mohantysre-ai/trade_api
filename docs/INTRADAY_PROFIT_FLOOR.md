# Intraday profit floor — 2026-09-02

The former 1R breakeven rule could close a trade for only 0.2R blended:
20% booked at 1R, with 80% stopped at entry. At 0.50% initial risk that is
only +0.10% on the original position. Two tranches at 1R and 1.5R followed
by breakeven produce +0.25%. Neither implies an EOD exit.

Policy `1r_scale_2r_trail_blended_1r_max_0p5pct`:

- Preserve the initial risk stop until the price reaches 2R.
- Book 20% at 1R, 20% at 1.5R, and 20% at 2R; retain 40% as a runner.
- At 2R, arm the existing monotonic price/R trail and enforce a floor of
  1R gross profit on the original full quantity, including actual rounded
  tranche quantities and booked P&L.
- An unresolved intraday position still exits at EOD at its actual mark,
  even below 1R. This is `EOD_SQUAREOFF`, not a target hit.
- Open paper positions with the legacy early-breakeven plan migrate their
  stop back to the original initial stop before 2R, retaining booked fills.
- Completed valid fills and their original policy are immutable in both
  the Book and EOD. Historical results are not improved by replaying them
  under the new policy.
- Swing retains its prior 1R breakeven policy.

1R is the original per-share risk, not 1%. At 0.50% initial risk, 2R is a
1% favorable price move. This is modeled paper execution, before fees and
slippage; it is not a guarantee of realized returns in live markets.

Deploy the updated backend and frontend together. Existing booked results
remain unchanged; the updated exit policy appears in the trade detail and
EOD policy labels. The NVIDIA retirement repair is documented separately
in `LLM_PROVIDER_ROUTING.md`.
