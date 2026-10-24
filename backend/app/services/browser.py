"""
Shared Selenium helpers: ad/tracker blocking and a hang-tolerant page load.
Used by extractor, downloader and translator.

Why this exists — wikicv pages load many third-party ad/analytics scripts.
Some never finish loading, so a plain `driver.get()` would block until
Selenium's HTTP client gave up with "Read timed out" (an uncatchable-looking
urllib3 error that kills the job). Three layers fix that:

  1. harden_options(): page_load_strategy='eager' makes driver.get() return
     at DOMContentLoaded (HTML parsed) instead of 'normal' = window.onload
     (every image/iframe/script done). We only need the DOM text.
  2. harden_driver(): uses the Chrome DevTools Protocol (CDP) — Chrome's
     internal debugging API, reachable via driver.execute_cdp_cmd() — to
     enable the Network domain and block requests matching AD_BLOCK_PATTERNS.
     Blocked requests fail instantly inside Chrome, so ads never load.
     It also sets a page-load timeout shorter than Selenium's own 120s.
  3. load_page(): if that timeout still fires, keep whatever DOM loaded and
     call window.stop() rather than failing the chapter.

Typical use (every module creates its Chrome through make_driver):
    driver = make_driver()            # visible Chrome, our UA, hardened
    inject_site_cookies(driver)       # log in to the book site with stored cookies
    load_page(driver, url)
"""
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from app.config import TRUYENWIKI, get_cookies, get_user_agent

# Ad/tracker URL patterns blocked in every Selenium session (Chrome DevTools
# Network.setBlockedURLs, '*' wildcards). Seen on wikicv book + chapter pages:
# tpmedia, gtag/GA, doubleclick, google.com.vn/pagead, facebook widget.
# The rest are common ad networks that ad scripts often load later.
# '*' matches any run of characters, so '*doubleclick.net*' blocks any URL
# containing that host, on any scheme/subdomain/path.
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
    """Return at DOMContentLoaded instead of waiting for every slow resource.

    Must be called BEFORE the driver is created (options are read at launch).

    Args:
        options: a selenium ChromeOptions (or compatible, e.g. undetected
            chromedriver options) instance.

    Returns:
        The same options object (mutated in place), so calls can be chained.
    """
    options.page_load_strategy = 'eager'
    return options


def harden_driver(driver):
    """Apply the page-load timeout and block ad/tracker requests.

    Call right after creating the driver, before the first driver.get().
    The CDP block list lasts for the life of this browser session.

    Args:
        driver: a live Chrome WebDriver (CDP commands are Chrome-only).

    Returns:
        The same driver, so `return harden_driver(webdriver.Chrome(...))` works.

    Side effects: sends CDP commands to the running Chrome.
    """
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    # Network.setBlockedURLs only works once the Network domain is enabled.
    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': AD_BLOCK_PATTERNS})
    return driver


def load_page(driver, url: str):
    """driver.get() that tolerates pages which never finish loading.

    Args:
        driver: a WebDriver hardened with harden_driver() (so a timeout is set).
        url: absolute URL to open.

    Returns:
        None. On timeout the partially loaded DOM is kept and still usable
        by find_element() calls; other WebDriver errors propagate to the caller.

    Side effects: navigates the browser (network traffic).
    """
    try:
        driver.get(url)
    except TimeoutException:
        print(f"⚠️ Page load timed out, using partially loaded DOM: {url}")
        # Abort the remaining network requests so the page stops changing
        # under us while we scrape it.
        driver.execute_script("window.stop();")


def make_driver(*, headless: bool = False, custom_ua: bool = True, harden: bool = True):
    """Create a Chrome WebDriver — the ONE place where the app builds a browser.

    The `*` in the signature makes every parameter keyword-only, so calls read
    clearly: `make_driver(headless=True)` instead of `make_driver(True)`.

    Args:
        headless: True = no visible window (login, text-cleaning test).
            The downloader/extractor/translator stay visible so you can watch
            them and solve a Cloudflare check by hand if needed.
        custom_ua: True = send the User-Agent from settings (get_user_agent()).
            The TRANSLATOR passes False: its cf_clearance cookie is bound to
            the exact UA of the browser that solved the Cloudflare challenge,
            so Chrome must keep its real UA there.
        harden: True = eager page loads + ad blocking + page-load timeout
            (see the module docstring). Login passes False to keep its
            original behaviour (login pages may need third-party scripts).

    Returns:
        A ready `webdriver.Chrome`. The caller owns it and must call
        `driver.quit()` when done (ideally in a `finally` block).
    """
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Hides the `navigator.webdriver` flag that some sites use to detect bots.
    options.add_argument("--disable-blink-features=AutomationControlled")
    if custom_ua:
        options.add_argument(f"user-agent={get_user_agent()}")
    if harden:
        harden_options(options)

    # ChromeDriverManager().install() downloads a chromedriver that matches the
    # installed Chrome version (cached after the first run) and returns its path.
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return harden_driver(driver) if harden else driver


def inject_site_cookies(driver, cookies: dict = None):
    """Log the browser in to the BOOK site by adding the stored cookies.

    Selenium can only set cookies for the domain of the page that is open
    right now, so we first load the site's home page, then add each cookie.

    Args:
        driver: a live WebDriver (from make_driver()).
        cookies: {name: value} to add; None = the primary account (get_cookies()).
            The downloader passes an extra account's cookies when it switches
            account after hitting the site's access limit.

    Side effects: one page load of the home page; cookies added to the session.
    Cookies that Chrome rejects are reported and skipped (never fatal).
    """
    load_page(driver, TRUYENWIKI['book_domain'])
    domain = TRUYENWIKI['cookie_domain']
    # `x if x is not None else y`: an empty dict {} is respected (adds nothing).
    for name, value in (cookies if cookies is not None else get_cookies()).items():
        if value:
            try:
                driver.add_cookie({'name': name, 'value': value, 'domain': domain})
            except Exception as e:
                print(f"⚠️ Could not add cookie {name}: {e}")
