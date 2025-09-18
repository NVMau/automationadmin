from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from loguru import logger
from playwright.async_api import async_playwright, Page

from .config import AppConfig, Credentials


@dataclass
class UpdateResult:
	employee_id: str
	pos_id: str
	success: bool
	old_pos: str | None = None
	new_pos: str | None = None
	error: str | None = None


async def login(page: Page, cfg: AppConfig, creds: Credentials) -> None:
	await page.goto(cfg.login_url, wait_until="domcontentloaded")
	await page.fill(cfg.selectors.username_input, creds.username)
	await page.fill(cfg.selectors.password_input, creds.password)
	await page.click(cfg.selectors.login_submit)
	await page.wait_for_load_state("networkidle")


async def refresh_page(page: Page, cfg: AppConfig) -> None:
	"""Refresh the page to ensure clean state"""
	logger.info("Refreshing page to ensure clean state...")
	await page.goto(cfg.employee_search_url, wait_until="domcontentloaded")
	await page.wait_for_timeout(2000)


async def update_employee_pos(page: Page, cfg: AppConfig, employee_id: str, pos_id: str, *, step_delay_ms: int = 0) -> str:
	"""Perform search -> select -> edit -> save. Returns old POS value read from #info."""
	# Navigate to the management page
	await page.goto(cfg.employee_search_url, wait_until="domcontentloaded")
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)

	# Clear any existing search first
	await page.fill("#sharing_key", "")
	await page.wait_for_timeout(500)
	
	# Fill search key and click search
	await page.fill("#sharing_key", employee_id)
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)
	await page.click("#doSearch")
	
	# Wait for search results with better error handling
	try:
		await page.wait_for_load_state("networkidle", timeout=20000)
	except Exception:
		logger.warning("Network idle timeout, continuing anyway...")
	
	# Check if we got "Không có dữ liệu" (No data) - user not found or no permission
	no_data_text = await page.locator("text=Không có dữ liệu").count()
	if no_data_text > 0:
		# Take screenshot for debugging permission issues
		await page.screenshot(path=f"debug_no_data_{employee_id}.png")
		raise ValueError(f"User not found or no permission to access employee_id: {employee_id}")
	
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)

	# Select the row whose "Tên đăng nhập" matches employee_id, then click its radio
	row_xpath = f"//tr[.//td[normalize-space()='{employee_id}']]"
	
	# Wait for search results to appear with retry logic
	max_retries = 3
	for retry in range(max_retries):
		try:
			await page.wait_for_selector(row_xpath, timeout=10000)
			break
		except Exception as e:
			if retry == max_retries - 1:
				# Take screenshot for debugging
				await page.screenshot(path=f"debug_search_{employee_id}_{retry}.png")
				# Check again if "Không có dữ liệu" appeared during retries
				no_data_check = await page.locator("text=Không có dữ liệu").count()
				if no_data_check > 0:
					raise ValueError(f"User not found or no permission to access employee_id: {employee_id}")
				else:
					raise ValueError(f"Could not find employee row for {employee_id} after {max_retries} retries: {e}")
			logger.warning(f"Retry {retry + 1}/{max_retries} waiting for search results for {employee_id}")
			await page.wait_for_timeout(2000)
			# Try refreshing the search
			await page.click("#doSearch")
			await page.wait_for_timeout(3000)
	
	row = page.locator(row_xpath).first
	row_text = await row.inner_text()
	logger.info(f"Search result row chosen for {employee_id}: {row_text[:200]}...")
	radio_in_row = row.locator("input[name='sharing_partner_rad']")
	await radio_in_row.click()
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)

	# Click edit button
	await page.click("#goEdit")
	await page.wait_for_load_state("domcontentloaded")
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)

	# Verify the form shows the correct employee_id
	sharing_key_value = await page.input_value("#sharing_key")
	if sharing_key_value.strip() != employee_id:
		raise ValueError(f"Form shows wrong user: expected '{employee_id}', got '{sharing_key_value}'")
	logger.info(f"Verified form shows correct user: {employee_id}")

	# Get current POS info, set new one
	info_selector = "#info"
	await page.wait_for_selector(info_selector, timeout=cfg.timeouts.default)
	old_value = await page.input_value(info_selector)
	await page.fill(info_selector, "")
	await page.fill(info_selector, pos_id)
	logger.info(f"{employee_id}: POS info will change from '{old_value}' to '{pos_id}'")
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)

	# Auto-accept confirm dialog when saving
	page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
	await page.click("#doEdit")
	await page.wait_for_load_state("networkidle")
	if step_delay_ms: await page.wait_for_timeout(step_delay_ms)
	return old_value


async def run_updates(cfg: AppConfig, creds: Credentials, rows: List[Tuple[str, str]], *, headless: bool = True, dry_run: bool = False, retries: int | None = None, retry_backoff_seconds: float | None = None, step_delay_ms: int = 0, slowmo_ms: int = 0) -> List[UpdateResult]:
	retries = cfg.retries if retries is None else retries
	retry_backoff_seconds = cfg.retry_backoff_seconds if retry_backoff_seconds is None else retry_backoff_seconds

	results: List[UpdateResult] = []
	async with async_playwright() as p:
		browser = await p.chromium.launch(headless=headless, slow_mo=slowmo_ms if slowmo_ms > 0 else None)
		context = await browser.new_context()
		page = await context.new_page()
		try:
			logger.info("Logging in to admin site...")
			await login(page, cfg, creds)
			logger.info("Login successful")
			for i, (employee_id, pos_id) in enumerate(rows):
				# Refresh page between users to avoid stale state
				if i > 0:
					await refresh_page(page, cfg)
				
				attempt = 0
				while True:
					try:
						logger.info(f"Updating employee_id={employee_id} -> pos_id={pos_id} (dry_run={dry_run})")
						if not dry_run:
							old_value = await update_employee_pos(page, cfg, employee_id, pos_id, step_delay_ms=step_delay_ms)
							results.append(UpdateResult(employee_id, pos_id, True, old_pos=old_value, new_pos=pos_id))
						else:
							results.append(UpdateResult(employee_id, pos_id, True, old_pos=None, new_pos=pos_id))
						break
					except Exception as e:  # noqa: BLE001 - surface any site errors
						attempt += 1
						if attempt > retries:
							logger.error(f"Failed updating {employee_id}: {e}")
							results.append(UpdateResult(employee_id, pos_id, False, error=str(e)))
							break
						logger.warning(f"Retry {attempt}/{retries} for {employee_id} after error: {e}")
						# Refresh page on retry to clear any stuck state
						await refresh_page(page, cfg)
						await asyncio.sleep(retry_backoff_seconds)
		finally:
			await context.close()
			await browser.close()
	return results
