"""
Shared Selenium helpers: ad/tracker blocking and a hang-tolerant page load.
Used by extractor, downloader and translator.
"""
from selenium.common.exceptions import TimeoutException

# Ad/tracker URL patterns blocked in every Selenium session (Chrome DevTools
# Network.setBlockedURLs, '*' wildcards). Seen on wikicv book + chapter pages:
# tpmedia, gtag/GA, doubleclick, google.com.vn/pagead, facebook widget.
# The rest are common ad networks that ad scripts often load later.
# ponytail: static blocklist, add hosts here if a new ad network slows pages down.
# Never add Cloudflare hosts (challenges.cloudflare.com) — the translator needs them.
AD_BLOCK_PATTERNS = [
    # Seen on wikicv
    '*tpmedia.online*',
    '*googletagmanager.com*',
    '*google-analytics.com*',
    '*analytics.google.com*',
    '*doubleclick.net*',
    '*/pagead/*',
    '*facebook.net*',
    '*graph.facebook.com*',
    '*fbcdn.net*',
    # Google ads
    '*googlesyndication.com*',
    '*googleadservices.com*',
    '*adservice.google.*',
    '*adtrafficquality.google*',
    # Common ad networks / trackers
    '*amazon-adsystem.com*',
    '*adnxs.com*',
    '*criteo.*',
    '*taboola.com*',
    '*outbrain.com*',
    '*popads.net*',
    '*popcash.net*',
    '*propellerads.com*',
    '*adsterra.com*',
    '*exoclick.com*',
    '*hilltopads.*',
    '*onclickads.net*',
    '*mgid.com*',
    '*pubmatic.com*',
    '*rubiconproject.com*',
    '*openx.net*',
    '*casalemedia.com*',
    '*scorecardresearch.com*',
    '*hotjar.com*',
    '*clarity.ms*',
    '*yandex.ru/metrika*',
    '*mc.yandex.*',
    # Vietnamese ad networks
    '*admicro.vn*',
    '*vcmedia.vn*',
    '*eclick.vn*',
    '*adtima.vn*',
    '*ambientplatform.vn*',
    '*novanet.vn*',
    '*yomedia.vn*',
    '*vlitag.com*',
]

# Must stay below Selenium's 120s HTTP read timeout so a hung page raises a
# catchable TimeoutException instead of "Read timed out".
PAGE_LOAD_TIMEOUT = 60


def harden_options(options):
    """Return at DOMContentLoaded instead of waiting for every slow resource."""
    options.page_load_strategy = 'eager'
    return options


def harden_driver(driver):
    """Apply the page-load timeout and block ad/tracker requests."""
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': AD_BLOCK_PATTERNS})
    return driver


def load_page(driver, url: str):
    """driver.get() that tolerates pages which never finish loading."""
    try:
        driver.get(url)
    except TimeoutException:
        print(f"⚠️ Page load timed out, using partially loaded DOM: {url}")
        driver.execute_script("window.stop();")
