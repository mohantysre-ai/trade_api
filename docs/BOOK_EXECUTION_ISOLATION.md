# Trading Book Execution Isolation

Production sets `BOOK_EXECUTION_ISOLATION=true`.

| Book | Decision owner | Durable state | Market refresh ownership |
|---|---|---|---|
| Intraday equities | Intraday engine / desk scheduler | `intraday_session.json` | Full equity snapshot |
| Index Options | Index hunt and paper supervisors | `index_options_radar.json`, `index_options_paper_book.json` | Dedicated leader-basket context and option provider caches |
| Swing | Swing V2 authoritative worker | V2 SQLite ledger, V2 session JSON and `swing_v2_market_context.json` | V2-only decision refresh |

Isolation rules:

- No book reconciles, deletes, excludes or mutates another book's trades.
- Index Options never launches or writes the full equity snapshot refresh.
- Index Options breadth uses `index_options_market_context.json`, populated from
  its own small Angel leader-basket/VIX request. Missing or stale context fails
  Index Options closed without falling back to Intraday data.
- Intraday never reads Swing locks or gives Swing candidates precedence.
- Swing V2 never reads Intraday locks.
- Swing V2 never reads or overwrites the Intraday equity snapshot.
- Scheduler and supervisor exceptions are contained inside their owning worker.
- EOD reports read each book's own immutable/durable source before aggregation.

The books may use the same configured broker account, so a broker-wide outage
can affect each independent request. Such an outage cannot make one book write
or invalidate another book's state.
