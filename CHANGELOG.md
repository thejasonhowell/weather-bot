# Changelog

## 2026-09-04

### Reliability fixes

- Track successful delivery separately for Bluesky and Telegram. Retry missing copies without resending successful copies, and update alert history and weather-post state only after all configured destinations succeed.
- Persist delivery status with atomic file replacement. Retry recent pending posts from the scheduler, with a 15-minute automatic replay window.
- Add connection and read timeouts to WeatherFlow requests and heartbeat checks.
- Reject empty, malformed, stale, or future-dated station observations. Use the station timestamp in America/Chicago rather than labeling old readings with the current time.
- Calculate rain events from increases in daily accumulation. Dry polls no longer extend an event; three dry hours separate events, and daily counter resets are handled.
- Queue manual signal commands and execute them from the scheduler instead of interrupting active network requests and state updates. Commands are handled on the next scheduler cycle.
- Return accurate Telegram delivery results, including image-to-text fallbacks.

### Verification

- Added nine isolated regression tests covering failed and partial delivery, persisted retries, observation validation, request timeouts, rain-event separation, and queued commands.
- Tests use mocked services and do not import or start the live bot.
- Run with `python3 -m unittest discover -s tests -v`.
