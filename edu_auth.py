"""
EDU Authentication Module
Handles Playwright-based authentication for eurodollar.university with session persistence
"""

import os
import json
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class EDUAuth:
    """Manages authentication and browser sessions for eurodollar.university"""
    
    SESSION_DIR = os.path.join(os.path.dirname(__file__), '.browser_session')
    SESSION_FILE = os.path.join(SESSION_DIR, 'state.json')
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.authenticated = False
    
    def _ensure_browser(self, headless: bool = True) -> BrowserContext:
        """Initialize browser if not already running, return context"""
        if self.context:
            return self.context
            
        os.makedirs(self.SESSION_DIR, exist_ok=True)
        
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        # Try to load existing session
        if os.path.exists(self.SESSION_FILE):
            try:
                self.context = self.browser.new_context(
                    storage_state=self.SESSION_FILE,
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                return self.context
            except Exception:
                pass
        
        self.context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        return self.context
    
    def _save_session(self):
        """Save browser session for future use"""
        if self.context:
            os.makedirs(self.SESSION_DIR, exist_ok=True)
            self.context.storage_state(path=self.SESSION_FILE)
    
    def check_auth_status(self) -> Tuple[bool, str]:
        """Check if we have a valid authenticated session"""
        if not os.path.exists(self.SESSION_FILE):
            return False, "No saved session found"
        
        try:
            self._ensure_browser(headless=True)
            page = self.context.new_page()
            
            # Navigate to a protected page
            page.goto('https://www.eurodollar.university/members-home', wait_until='networkidle', timeout=30000)
            
            # Check if we got redirected to login
            if '/account/login' in page.url.lower() or 'sign_in' in page.url.lower():
                page.close()
                return False, "Session expired, please log in again"
            
            # Check for member content indicators
            content = page.content().lower()
            if 'welcome' in content or 'member' in content:
                self.authenticated = True
                page.close()
                return True, "Session valid"
            
            page.close()
            return False, "Could not verify session"
            
        except Exception as e:
            return False, f"Session check failed: {str(e)}"
    
    def login(self, email: str, password: str, headless: bool = False) -> Tuple[bool, str]:
        """
        Login to eurodollar.university with email and password.
        If headless=False, opens a visible browser for manual intervention if needed.
        """
        try:
            # Close any existing browser
            self.close()
            
            # Launch browser (visible for first-time login)
            self._ensure_browser(headless=headless)
            page = self.context.new_page()
            
            # Navigate to login page
            page.goto('https://www.eurodollar.university/account/login', wait_until='networkidle', timeout=30000)
            
            # Wait for login form
            page.wait_for_timeout(2000)
            
            # Check if already logged in
            if '/account/login' not in page.url.lower():
                self._save_session()
                self.authenticated = True
                page.close()
                return True, "Already logged in! Session saved."
            
            # Look for login form in iframe or main page
            try:
                # Try to find email field (may be in iframe)
                email_field = page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i]').first
                if email_field.count() == 0:
                    # Try iframe
                    frame = page.frame_locator('iframe').first
                    email_field = frame.locator('input[type="email"], input[name="email"], textbox[name="Email"]').first
                    password_field = frame.locator('input[type="password"], input[name="password"]').first
                    submit_btn = frame.locator('button[type="submit"], button:has-text("Sign in")').first
                else:
                    password_field = page.locator('input[type="password"], input[name="password"]').first
                    submit_btn = page.locator('button[type="submit"], button:has-text("Sign in")').first
                
                # Fill credentials
                email_field.fill(email)
                page.wait_for_timeout(500)
                password_field.fill(password)
                page.wait_for_timeout(500)
                
                # Submit
                submit_btn.click()
                
                # Wait for navigation
                page.wait_for_timeout(5000)
                
                # Check if login succeeded
                if '/account/login' not in page.url.lower() and 'sign_in' not in page.url.lower():
                    self._save_session()
                    self.authenticated = True
                    page.close()
                    return True, "Login successful! Session saved."
                else:
                    # Check for error message
                    error_text = page.locator('.error, .alert, [role="alert"]').first
                    if error_text.count() > 0:
                        error_msg = error_text.text_content()
                        page.close()
                        return False, f"Login failed: {error_msg}"
                    page.close()
                    return False, "Login failed - please check credentials"
                    
            except Exception as e:
                page.close()
                return False, f"Could not find login form: {str(e)}"
                
        except Exception as e:
            return False, f"Login error: {str(e)}"
    
    def login_interactive(self) -> Tuple[bool, str]:
        """
        Open a visible browser for manual login.
        User completes login manually, then session is saved.
        """
        try:
            self.close()
            self._ensure_browser(headless=False)
            page = self.context.new_page()
            
            page.goto('https://www.eurodollar.university/account/login', wait_until='networkidle')
            
            # Check if already logged in
            if '/account/login' not in page.url.lower():
                self._save_session()
                self.authenticated = True
                page.close()
                return True, "Already logged in! Session saved."
            
            print("\n" + "="*50)
            print("MANUAL LOGIN REQUIRED")
            print("="*50)
            print("A browser window has opened.")
            print("Please log in with your credentials.")
            print("Waiting up to 2 minutes for login...")
            print("="*50 + "\n")
            
            # Wait for redirect away from login page
            try:
                page.wait_for_url(
                    lambda url: '/account/login' not in url.lower() and 'sign_in' not in url.lower(),
                    timeout=120000
                )
            except Exception:
                page.close()
                return False, "Login timed out. Please try again."
            
            page.wait_for_timeout(2000)
            self._save_session()
            self.authenticated = True
            page.close()
            
            return True, "Login successful! Session saved for future downloads."
            
        except Exception as e:
            return False, f"Interactive login error: {str(e)}"
    
    def get_page(self) -> Page:
        """Get a new page with authenticated context"""
        if not self.context:
            self._ensure_browser(headless=True)
        return self.context.new_page()
    
    def get_cookies(self) -> dict:
        """Get cookies as a dict for requests library"""
        if not self.context:
            return {}
        cookies = {}
        for cookie in self.context.cookies():
            cookies[cookie['name']] = cookie['value']
        return cookies
    
    def get_cookie_string(self, domain_filter: str = 'eurodollar') -> str:
        """Get cookies as a string for ffmpeg headers"""
        if not self.context:
            return ""
        cookie_parts = []
        for c in self.context.cookies():
            if domain_filter in c.get('domain', ''):
                cookie_parts.append(f"{c['name']}={c['value']}")
        return "; ".join(cookie_parts)
    
    def close(self):
        """Clean up browser resources"""
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        
        self.context = None
        self.browser = None
        self.playwright = None
        self.authenticated = False

