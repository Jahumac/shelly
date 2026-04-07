# Contributing to Shelly

Thanks for your interest in contributing! Shelly is a personal project shared with the community, and contributions are welcome.

## Reporting Issues

If you find a bug or have a feature request, please open a GitHub issue. Include as much detail as you can — steps to reproduce, expected vs actual behaviour, and screenshots if relevant.

## Pull Requests

1. Fork the repo and create your branch from `main`.
2. Keep changes focused — one feature or fix per PR.
3. Test your changes locally (`python run.py` or `docker compose up`).
4. Make sure the app runs without errors on a fresh database (delete `data/finance.db` and go through the setup flow).
5. Write a clear PR description explaining what you changed and why.

## Code Style

- Python: Follow PEP 8. No linter is enforced yet, but keep things tidy.
- Templates: Jinja2 with HTML. Use the existing naming and indentation conventions.
- CSS: All styles live in `app/static/css/styles.css`. Use CSS custom properties (variables) defined at the top of the file.
- JavaScript: Vanilla JS, no build step. Keep scripts inline in templates where they only apply to one page.

## Database Migrations

Shelly uses SQLite with auto-migrations in `app/models.py` (`init_db()`). If your change adds a column or table, add a migration block following the existing pattern — check for the column/table first, then ALTER/CREATE if it doesn't exist. This keeps the upgrade path smooth for existing users.

## What Makes a Good Contribution

- Bug fixes (especially edge cases around projections, fees, or CSV import)
- New broker CSV parsers (see `app/services/csv_parsers.py` for examples)
- Accessibility improvements
- Performance improvements
- Documentation fixes

## What to Avoid

- Adding external services or cloud dependencies (Shelly is local-first by design)
- Large refactors without discussion — open an issue first
- Changes that break the single-file SQLite architecture

## Questions?

Open an issue or start a discussion. No question is too small.
