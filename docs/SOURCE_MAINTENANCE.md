# Source Registry Maintenance

The registry is `data/australian_defence_source_universe.xlsx`. It is the single source of truth
for what Kestrel scans. Edit in Excel; no code changes needed.

- **Re-verify URLs quarterly.** Update `Last Verified Date`.
- **Deactivate** stale sources (`Active = No`) after ~12 months of no useful output.
- **Add** newly relevant companies after major contracts, listings or funding rounds.
- **Review tiers** after each event cycle (Avalon, Land Forces, Indo Pacific, budget season).
- **Slot routing:** `Include in Morning Digest` / `Include in Afternoon Digest` control which run
  scans a source. Morning favours official + ASX + overnight; afternoon favours company/state/trade.
- **Scrape hints:** put `selector: <css selector>` in the `Notes` column for fragile HTML sources.
