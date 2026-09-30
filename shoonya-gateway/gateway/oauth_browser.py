from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlencode, urlparse

import pyotp

from .auth_types import OAuthBrowserUnavailable


def _authorization_code(driver):
    current = urlparse(driver.current_url)
    code = parse_qs(current.query).get("code", [None])[0]
    if code:
        return code
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
            if message.get("method") != "Network.requestWillBeSent":
                continue
            url = message.get("params", {}).get("request", {}).get("url", "")
            code = parse_qs(urlparse(url).query).get("code", [None])[0]
            if code:
                return code
        except (KeyError, TypeError, ValueError):
            continue
    return None


def fetch_authorization_code(settings):
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as ec
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise OAuthBrowserUnavailable("Selenium is unavailable") from exc
    required = (settings.uid, settings.password, settings.totp_secret, settings.vendor_code)
    if not all(required):
        raise OAuthBrowserUnavailable("OAuth browser credentials are incomplete")
    options = webdriver.ChromeOptions()
    for option in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1280,900",
    ):
        options.add_argument(option)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, settings.oauth_browser_timeout_s)
    try:
        query = urlencode({"api_key": settings.vendor_code, "route_to": settings.uid})
        driver.get(f"{settings.oauth_login_url}?{query}")
        wait.until(ec.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']")))
        inputs = [
            item
            for item in driver.find_elements(
                By.CSS_SELECTOR,
                "input:not([type='hidden']):not([type='checkbox']):not([type='radio'])",
            )
            if item.is_displayed()
        ]
        if len(inputs) < 3:
            raise OAuthBrowserUnavailable("Shoonya login form shape changed")
        for element, value in zip(
            inputs[:3],
            (settings.uid, settings.password, pyotp.TOTP(settings.totp_secret).now()),
        ):
            element.clear()
            element.send_keys(value)
        wait.until(
            ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='LOGIN']"))
        ).click()
        deadline = time.monotonic() + settings.oauth_browser_timeout_s
        while time.monotonic() < deadline:
            code = _authorization_code(driver)
            if code:
                return code
            time.sleep(0.5)
        raise OAuthBrowserUnavailable("Shoonya OAuth redirect code was not observed")
    finally:
        driver.quit()
