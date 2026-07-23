"""
Auto-login service using Selenium.
Follows the actual site login flow:
1. Go to homepage
2. Click login trigger (opens modal)
3. Fill credentials
4. Submit form
5. Extract cookies
"""
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from app.database import get_database
from app.config import TRUYENWIKI, COOKIE_KEYS, get_user_agent


class AutoLogin:
    def __init__(self):
        self.db = get_database()
        self.driver = None
        self._load_config()

    def _load_config(self):
        """Load login configuration from DB."""
        self.login_url = self.db.get_setting('login_url', 'https://forum.dichtienghoa.com/login')
        self.login_domain = self.db.get_setting('login_domain', 'forum.dichtienghoa.com')
        self.trigger_selector = self.db.get_setting('login_trigger_selector', 'a[data-action="login"]')

    def _save_config(self):
        """Save login configuration to DB."""
        self.db.update_setting('login_url', self.login_url)
        self.db.update_setting('login_domain', self.login_domain)
        self.db.update_setting('login_trigger_selector', self.trigger_selector)

    def _setup_selenium(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument(f"user-agent={get_user_agent()}")
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        return driver

    def _extract_cookies(self):
        """Extract all relevant cookies from the current browser session."""
        all_cookies = self.driver.get_cookies()
        extracted = {}
        for cookie in all_cookies:
            if cookie['name'] in COOKIE_KEYS:
                extracted[cookie['name']] = cookie['value']
        return extracted

    def _save_cookies(self, cookies):
        """Save extracted cookies to database."""
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
        """
        self.driver = self._setup_selenium()
        try:
            self.db.update_setting("account_username", username)
            self.db.update_setting("account_password", password)

            homepage = TRUYENWIKI['book_domain']
            print(f"Navigating to homepage: {homepage}")
            self.driver.get(homepage)
            time.sleep(3)

            # Step 1: Click the login trigger
            print(f"Looking for login trigger: {self.trigger_selector}")
            try:
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
            # The form might be in an iframe or in the main page
            # Try to find iframes first
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            login_frame = None
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if 'login' in src.lower() or self.login_domain in src:
                    login_frame = iframe
                    break

            if login_frame:
                print("Switching to login iframe")
                self.driver.switch_to.frame(login_frame)
                time.sleep(2)

            # Step 3: Handle potential popup/window switch
            # If clicking the trigger opened a new window/tab
            if len(self.driver.window_handles) > 1:
                print("Switching to new popup window")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(2)

            # Step 4: Wait for and fill the login form
            print("Looking for login form fields...")
            wait = WebDriverWait(self.driver, 10)

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
                    continue

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
                from selenium.webdriver.common.keys import Keys
                pass_input.send_keys(Keys.RETURN)
                print("Pressed Enter to submit")

            # Step 6: Wait for login to complete
            time.sleep(5)

            # Step 7: Switch back to main window if we switched
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[0])
                time.sleep(2)

            # Step 8: Navigate to both domains to collect all cookies
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

            # Extract cookies from book domain
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
            if self.driver:
                self.driver.quit()
                self.driver = None


def auto_login(username: str, password: str) -> dict:
    """Convenience function for auto-login."""
    service = AutoLogin()
    return service.perform_login(username, password)
