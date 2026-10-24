"""
Auto-login service using Selenium.

Logs into the book site with a username/password in a headless Chrome and
harvests the session cookies the downloader needs.

Login flow (see AutoLogin.perform_login for details):
1. Go to the homepage.
2. Click the login trigger (opens a modal) — or, if it is missing, navigate
   straight to the login URL.
3. Switch into the login iframe / popup window if the form lives there.
4. Fill the credentials (several selector guesses, first match wins).
5. Submit the form (submit button, or Enter as fallback).
6. Extract cookies from the login domain AND the book domain, and save the
   known ones (COOKIE_KEYS) into the settings table as `cookie_<name>`.
"""
import json
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from app.database import get_database
from app.config import TRUYENWIKI, COOKIE_KEYS
from app.services.browser import make_driver


class AutoLogin:
    """One-shot Selenium login helper.

    Create an instance and call perform_login(); the Chrome driver is created
    inside perform_login and always quit before it returns.

    Attributes:
        db: the shared Database instance (settings read/write).
        driver: the Selenium WebDriver while a login is running, else None.
        login_url / login_domain / trigger_selector: loaded from DB settings.
    """

    def __init__(self, account_id: int = None):
        """Load the DB handle and login settings. No browser is started yet.

        Args:
            account_id: id of an extra `site_accounts` row to save the cookies
                to. None = the primary account (the `cookie_<name>` settings).
        """
        self.db = get_database()
        self.driver = None
        self.account_id = account_id
        self._load_config()

    def _load_config(self):
        """Load login configuration from DB settings (with built-in defaults).

        Side effects:
            Sets self.login_url, self.login_domain and self.trigger_selector.
        """
        # get_setting(key, default): the second argument is used when the key is unset.
        self.login_url = self.db.get_setting('login_url', 'https://forum.dichtienghoa.com/login')
        self.login_domain = self.db.get_setting('login_domain', 'forum.dichtienghoa.com')
        self.trigger_selector = self.db.get_setting('login_trigger_selector', 'a[data-action="login"]')

    def _save_cookies(self, cookies):
        """Save extracted cookies to the database.

        Args:
            cookies: dict of cookie name -> value.

        Side effects:
            DB write: for an extra account, its `site_accounts.cookies` JSON;
            otherwise one setting `cookie_<name>` per cookie.
        """
        if self.account_id is not None:
            # json.dumps turns the dict into JSON text for the TEXT column.
            self.db.set_site_account_cookies(self.account_id, json.dumps(cookies))
            print(f"Saved {len(cookies)} cookies to extra account id={self.account_id}")
            return
        for name, value in cookies.items():
            self.db.update_setting(f"cookie_{name}", value)
            print(f"Saved cookie: {name}")

    def perform_login(self, username: str, password: str) -> dict:
        """
        Perform the full auto-login flow.

        Steps:
        1. Go to homepage
        2. Click on login trigger (e.g., a[data-action="login"])
        3. Wait for login modal/form to appear
        4. Fill username and password
        5. Submit the form
        6. Wait for login to complete
        7. Extract and save cookies

        Args:
            username: account username / email.
            password: account password.

        Returns:
            dict: {"success": bool, "message": str}. Errors are caught and
            returned as success=False rather than raised.

        Side effects:
            Starts (and always quits) a headless Chrome; network access to the
            book/login sites; DB writes of account_username, account_password
            and the extracted `cookie_<name>` settings.
        """
        # Headless Chrome (no window). harden=False keeps the original login
        # behaviour: no ad-blocking, normal page loads (login pages may rely
        # on third-party scripts).
        self.driver = make_driver(headless=True, harden=False)
        try:
            # TODO: account_password is stored in plaintext in the settings
            # table; encrypt it or stop storing it (PLAN.md Phase 3).
            # Extra accounts already keep their credentials in site_accounts.
            if self.account_id is None:
                self.db.update_setting("account_username", username)
                self.db.update_setting("account_password", password)

            homepage = TRUYENWIKI['book_domain']
            print(f"Navigating to homepage: {homepage}")
            self.driver.get(homepage)
            # TODO: fixed sleeps here and below are slow and flaky; replace
            # with WebDriverWait conditions.
            time.sleep(3)

            # Step 1: Click the login trigger
            print(f"Looking for login trigger: {self.trigger_selector}")
            try:
                # WebDriverWait(...).until(condition) polls until the condition
                # returns an element, or raises TimeoutException after 10s.
                login_trigger = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, self.trigger_selector))
                )
                login_trigger.click()
                print("Login trigger clicked")
                time.sleep(3)
            except TimeoutException:
                # If trigger not found, try navigating directly to login URL
                print(f"Trigger not found, navigating directly to: {self.login_url}")
                self.driver.get(self.login_url)
                time.sleep(3)

            # Step 2: Switch to the login form
            # The form might be in an iframe or in the main page.
            # Selenium can only see elements of the current frame, so if the
            # form is inside an iframe we must switch into it first.
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            login_frame = None
            for iframe in iframes:
                # `or ''` guards against get_attribute returning None.
                src = iframe.get_attribute('src') or ''
                if 'login' in src.lower() or self.login_domain in src:
                    login_frame = iframe
                    break

            if login_frame:
                print("Switching to login iframe")
                self.driver.switch_to.frame(login_frame)
                time.sleep(2)

            # Step 3: Handle potential popup/window switch
            # If clicking the trigger opened a new window/tab, the newest
            # handle is the last one in the list.
            if len(self.driver.window_handles) > 1:
                print("Switching to new popup window")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(2)

            # Step 4: Wait for and fill the login form
            print("Looking for login form fields...")
            wait = WebDriverWait(self.driver, 10)

            # Try several selector guesses; the first one that matches wins.
            # Note: each failed guess waits up to 10s, so a late match is slow.
            user_input = None
            user_selectors = [
                'input[name="username"]', 'input[name="email"]', 'input[name="login"]',
                'input[id*="user"]', 'input[type="email"]',
                'input[placeholder*="email" i]', 'input[placeholder*="user" i]',
                'input[placeholder*="tài khoản" i]'
            ]
            for sel in user_selectors:
                try:
                    user_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    break
                except:
                    # TODO: bare `except:` also swallows KeyboardInterrupt;
                    # catch (TimeoutException, NoSuchElementException) instead.
                    continue

            # The password field is looked up without waiting: by now the form
            # is known to be present (the username field was found).
            pass_input = None
            pass_selectors = [
                'input[name="password"]', 'input[type="password"]',
                'input[id*="pass"]', 'input[placeholder*="pass" i]',
                'input[placeholder*="mật khẩu" i]'
            ]
            for sel in pass_selectors:
                try:
                    pass_input = self.driver.find_element(By.CSS_SELECTOR, sel)
                    break
                except:
                    continue

            if not user_input or not pass_input:
                return {"success": False, "message": "Could not find username/password fields on login form."}

            user_input.clear()
            user_input.send_keys(username)
            pass_input.clear()
            pass_input.send_keys(password)
            print("Login form filled")

            # Step 5: Submit the form
            time.sleep(1)
            submit_btn = None
            # Mixed list: entries starting with '//' are XPath (needed for
            # "button containing text", which CSS cannot express), the rest CSS.
            submit_selectors = [
                'button[type="submit"]', 'input[type="submit"]',
                '//button[contains(text(), "Đăng nhập")]',
                '//button[contains(text(), "Login")]',
                '//button[contains(text(), "Đăng")]'
            ]
            for sel in submit_selectors:
                try:
                    if sel.startswith('//'):
                        submit_btn = self.driver.find_element(By.XPATH, sel)
                    else:
                        submit_btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                    break
                except:
                    continue

            if submit_btn:
                submit_btn.click()
                print("Submit button clicked")
            else:
                # No button found: pressing Enter in the password field submits
                # the surrounding <form>.
                from selenium.webdriver.common.keys import Keys
                pass_input.send_keys(Keys.RETURN)
                print("Pressed Enter to submit")

            # Step 6: Wait for login to complete
            time.sleep(5)

            # Step 7: Switch back to main window if we switched
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[0])
                time.sleep(2)

            # Step 8: Navigate to both domains to collect all cookies.
            # driver.get_cookies() only returns cookies for the CURRENT page's
            # domain, so we read them on the login domain and the book domain.
            extracted = {}

            # First, extract cookies from current page (login domain — may have express.sid etc.)
            print(f"Extracting cookies from current page ({self.driver.current_url})...")
            for cookie in self.driver.get_cookies():
                if cookie['name'] in COOKIE_KEYS:
                    extracted[cookie['name']] = cookie['value']
                    print(f"Found cookie: {cookie['name']} (domain: {cookie.get('domain', 'N/A')})")

            # Then navigate to book domain to collect domain-wide cookies
            print(f"Navigating to {TRUYENWIKI['book_domain']} to collect domain cookies...")
            self.driver.get(TRUYENWIKI['book_domain'])
            time.sleep(5)

            # Extract cookies from book domain (login-domain values win on duplicates)
            print("Extracting cookies from book domain...")
            for cookie in self.driver.get_cookies():
                if cookie['name'] in COOKIE_KEYS and cookie['name'] not in extracted:
                    extracted[cookie['name']] = cookie['value']
                    print(f"Found cookie: {cookie['name']} (domain: {cookie.get('domain', 'N/A')})")

            if extracted:
                self._save_cookies(extracted)
                return {
                    "success": True,
                    "message": f"Login successful. Extracted {len(extracted)} cookies: {', '.join(extracted.keys())}."
                }
            else:
                return {
                    "success": False,
                    "message": "Login completed but no known cookies were found. The login might have failed."
                }

        except Exception as e:
            return {"success": False, "message": f"Auto-login error: {str(e)}"}
        finally:
            # `finally` runs even after `return`, so Chrome is always closed.
            if self.driver:
                self.driver.quit()
                self.driver = None


def auto_login(username: str, password: str, account_id: int = None) -> dict:
    """Convenience function for auto-login.

    Args:
        username: account username / email.
        password: account password.
        account_id: extra `site_accounts` row to save the cookies to;
            None = primary account (`cookie_<name>` settings).

    Returns:
        dict: {"success": bool, "message": str} from AutoLogin.perform_login.

    Side effects:
        See AutoLogin.perform_login (browser, network, DB writes).
    """
    service = AutoLogin(account_id)
    return service.perform_login(username, password)

