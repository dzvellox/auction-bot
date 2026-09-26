from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_marketplace_id: str = "EBAY_FR"
    ebay_currency: str = "EUR"

    enable_ebay: bool = True
    enable_interencheres: bool = True
    enable_agorastore: bool = True
    enable_catawiki: bool = True

    # Interencheres: MAX_PAGES is an upper bound. If the website signals that
    # pagination is actually finished before that (416 / repeated empty pages),
    # there is nothing useful to fetch beyond it.
    interencheres_max_pages: int = 100
    interencheres_max_retries: int = 2
    interencheres_timeout_seconds: float = 30.0
    # V7 follows the reference repo more closely: random 2-5 s delay between
    # pages and 10 s after a 403/session reset.  The older
    # INTERENCHERES_PAGE_DELAY_SECONDS is intentionally no longer used.
    interencheres_page_delay_seconds: float = 0.8  # legacy / ignored by V7 adapter
    interencheres_empty_page_tolerance: int = 2  # legacy / ignored by V7 adapter
    interencheres_page_delay_min_seconds: float = 2.0
    interencheres_page_delay_max_seconds: float = 5.0
    interencheres_blocked_retry_delay_seconds: float = 10.0
    interencheres_retry_delay_seconds: float = 5.0  # legacy V7 / no longer used by V8

    # V8: public category pages instead of the blocked /recherche/lots route.
    interencheres_category_top_k: int = 4
    interencheres_category_page_delay_seconds: float = 0.25
    # Optional connection to a *real local* Chrome/Edge session.  The helper in
    # tools/ starts a dedicated browser with this debugging port.  Human
    # verification, if any, must be completed manually in that browser.
    interencheres_cdp_url: str | None = "http://127.0.0.1:9222"
    interencheres_browser_timeout_ms: int = 30000
    interencheres_browser_settle_ms: int = 1200
    interencheres_browser_page_retries: int = 2
    interencheres_browser_retry_delay_seconds: float = 1.0
    # V8.4: when the local CDP browser is already running, use it directly
    # instead of first generating a guaranteed 403 with httpx on every page.
    interencheres_prefer_cdp: bool = True
    interencheres_cdp_health_timeout_seconds: float = 2.0
    interencheres_cdp_direct_settle_ms: int = 350
    interencheres_cdp_direct_page_delay_seconds: float = 0.05
    interencheres_progress_every_pages: int = 10

    # Catawiki: exact current prices are enriched from each lot detail page.
    catawiki_max_results: int = 40
    catawiki_detail_concurrency: int = 4

    # Agorastore is now a JS-heavy SPA. Search + detail pages are rendered in
    # Playwright when the lightweight HTTP response is only a shell.
    agorastore_max_results: int = 40
    agorastore_detail_concurrency: int = 3

    enable_browser_fallback: bool = True
    browser_headless: bool = True
    browser_channel: str | None = "msedge"
    browser_timeout_ms: int = 30000

    database_url: str = "sqlite:///./auction_bot.db"
    min_scan_interval: int = 60
    default_scan_interval: int = 300
    notify_existing_on_first_scan: bool = True
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
