# Kestrel Operator Runbook (v1)

## Daily flow
1. Tasks fire at 07:00 and 11:30 (Australia/Sydney). The machine must be on or able to wake.
2. Each run writes to `output/YYYY-MM-DD/`. Open `kestrel_<slot>_<date>.html` to review.
3. In `fallback` mode, also open `...digest.md` and fill the `[[PASTE FROM CLAUDE]]` blocks
   (Top Line, KPMG angles, Watchpoints) using Claude, then re-save the HTML.
4. Read the console summary for `needs_attention` sources and the suggested recipient count.
5. Forward the HTML to the partner distribution. Subject line is in `subject.txt`.

## Missed run
If the machine was off, the next time Kestrel starts it detects the missed slot, generates the
brief late, and stamps the header `LATE RUN — generated HH:MM`. Review and send as normal.

## When a source stops producing
A source flagged `needs_attention` twice usually has a changed page layout. Open the registry,
find the row, and add or fix a `selector: ...` hint in the Notes column. Re-run with
`scripts\run_once.ps1`.

## Turning on the model
When the API key is approved: put it in `.env`, set `synthesis.provider: anthropic` in
`config/kestrel.yaml`, and re-run. The `[[PASTE FROM CLAUDE]]` placeholders disappear.
