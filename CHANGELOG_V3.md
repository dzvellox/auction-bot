# V3 fixes

- First `/add` now sends matching auctions already online.
- Interencheres: Live, Chrono and Catalogue classification.
- Interencheres: fixed-time labels (`À 18h00`, `Demain à ...`, dated sales) are included in Telegram alerts.
- Interencheres estimates are no longer mislabeled as current prices.
- 403/429 fallback through Playwright (Edge/Chromium) for public JS pages.
- Catawiki benefits from the same browser fallback.
- CAPTCHA/human-verification pages are not bypassed; the source fails cleanly.
- Temporary source failures log concise warnings instead of full expected 403 stack traces.
- Telegram first-scan bursts are lightly throttled to reduce flood-limit errors.
- Added `/reset ID` to clear one watch history and immediately resend current matches.
- Deleting a watch now explicitly clears SeenItem rows to avoid stale anti-duplicate records.
