# Changelog

All notable changes to this project will be documented in this file.

## [1.8.0] - 2026-04-20

### Added
- **Professional Pricing Engine**: Integrated Twelve Data API as the primary source for high-reliability live prices.
- **Currency Intelligence**: Automatic FX conversion for USD and EUR holdings into GBP account values.
- **Security Hardening**:
    - Cryptographically hashed API tokens (SHA-256).
    - Strict Content Security Policy (CSP) with no inline JavaScript.
    - Global API rate limiting (60 req/min).
    - Optional Redis support for shared rate limiting across multiple instances.
- **Manual Refresh Cooldown**: 3-minute cooldown to prevent API credit burn and server race conditions.
- **Improved Observability**: Detailed provider breakdown (TwelveData, Yahoo, etc.) in the refresh success banner.

### Fixed
- **Atomic Transactions**: Background price updates and holding syncs are now wrapped in SQL transactions to prevent data corruption.
- **"Stuck Price" Bug**: Normalized database timestamps to ensure the Overview page always reflects the true latest update.
- **Browser Caching**: Added strict `Cache-Control` headers to prevent stale HTML views after refreshes.
- **Maintenance Safety**: Implemented `ON DELETE CASCADE` across the schema for automatic and safe data cleanup.
- **Concurrency Safety**: Database migrations are now multi-worker safe, preventing race conditions during container startup.

### Changed
- **Modular Assets**: Moved all inline JavaScript logic to a dedicated external `app.js` file.
- **Neutral Branding**: Updated UI wording from "Yahoo Finance" to "live market data providers" to reflect the new multi-source capability.
