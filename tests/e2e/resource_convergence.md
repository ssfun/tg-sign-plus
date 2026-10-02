# Resource convergence acceptance

Failure scenarios, written before implementation:

- Authentication keeps a checked-out connection during Telegram awaits or a
  WebSocket stream. Invalid/deleted users must still be rejected; password,
  username and TOTP mutations must continue to persist in their transaction.
- Cold account listing performs N+1 queries or selects session secrets. Pending
  logins must remain hidden; account ordering/profile fields must not change.
- A forced chat refresh loads both old and new full ORM lists. Metadata-only
  requests must load none, ordinary reads must remain backwards compatible,
  expired/absent caches must refresh and valid empty caches must not refetch.
  Busy accounts must return cached data for automatic refresh and conflict for
  explicit refresh. Transport failures must not discard the old cache.
- Completed chats keep retaining Message objects through the old message store.
  Active event runners must still receive new and edited messages, and draining
  must release pending message tasks. Existing event-engine acceptance covers
  calculation/image/poetry/terminal-result behavior.
  Preserve the incoming-reply log format consumed by the saved run summary.
- The chat picker loads/renders every chat twice. It must show one page of at
  most 50 items, support search and paging, preserve a selected/manual chat,
  and fence delayed results after search/page/account/dialog changes. Closing
  or refreshing must abort obsolete reads. A failed refresh must remain retryable.
  If an explicit refresh fails after a successful page load, preserve that page,
  selected/manual chat and metadata; cached search and paging must still work
  while Telegram remains unavailable. Also cover refresh during a pending search.

Run at final acceptance, with runtime dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python tests/e2e/resource_convergence.py --output /tmp/convergence
PYTHONDONTWRITEBYTECODE=1 python tests/e2e/resource_efficiency.py --output /tmp/efficiency
```

Both use isolated SQLite and synthetic Telegram transports. Receipts are JSON;
no real account or production database is used. Browser acceptance uses the
convergence server's `--serve PORT` mode and the built `frontend/out` directory.

For browser reproduction:

1. Build the frontend, then run `python tests/e2e/resource_convergence.py
   --output /tmp/convergence/browser --serve 18766`.
2. In an ego-browser TaskSpace, use a nonzero viewport, log in at
   `http://127.0.0.1:18766` with the synthetic user `review` / `Review123!`,
   and open `/dashboard/account-tasks?name=acct00&new=1`.
3. Import `tests/e2e/chat_picker_browser.mjs` in the ego-browser Node runtime.
   Call `verifyChatPicker(page, '/tmp/convergence')` and then
   `verifyChatPickerRaces(page, '/tmp/convergence')` on the same Page.
   The helpers record bounded rows, selection, retry, actual request aborts,
   account switching, desktop/mobile geometry and DOM snapshots.
4. Finish the TaskSpace and stop the isolated server. The helpers do not send
   Telegram messages or execute sign tasks.
