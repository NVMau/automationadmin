from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, List, Tuple

import csv

import typer
from loguru import logger

from .config import load_config, load_credentials
from .excel_reader import read_employee_pos_pairs
from .automation import run_updates, login
from playwright.async_api import async_playwright

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _parse_pairs(pairs: List[str]) -> List[Tuple[str, str]]:
	result: List[Tuple[str, str]] = []
	for item in pairs:
		if "=" not in item:
			raise typer.BadParameter(f"Invalid pair format: {item}. Use EMP=POS")
		emp, pos = item.split("=", 1)
		emp = emp.strip()
		pos = pos.strip()
		if not emp or not pos:
			raise typer.BadParameter(f"Invalid pair (empty values): {item}")
		result.append((emp, pos))
	return result


def _setup_file_logging(log_file: Optional[str]) -> None:
	if not log_file:
		return
	logger.add(log_file, rotation="2 MB", retention=5, enqueue=True, encoding="utf-8")
	logger.info(f"File logging enabled: {log_file}")


def _write_audit_csv(path: Optional[str], results) -> None:
	if not path:
		return
	p = Path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	with p.open("w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(["employee_id", "old_pos", "new_pos", "success", "error"])
		for r in results:
			writer.writerow([r.employee_id, r.old_pos or "", r.new_pos or "", "true" if r.success else "false", r.error or ""])
	logger.info(f"Audit CSV written: {p}")


def _write_invalid_csv(path: Optional[str], invalid_pairs: List[Tuple[str, str]]) -> None:
	"""Write users with missing POS data to CSV for review."""
	if not path:
		path = "logs/invalid_users.csv"
	p = Path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	with p.open("w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(["employee_id", "pos_id", "reason"])
		for emp_id, pos_id in invalid_pairs:
			reason = "Missing POS data" if not pos_id or pos_id.lower() in ["#n/a", "nan", "none", ""] else "Invalid POS format"
			writer.writerow([emp_id, pos_id, reason])
	logger.info(f"Invalid users CSV written: {p}")


def _write_permission_denied_csv(path: Optional[str], denied_users: List[str]) -> None:
	"""Write users with permission denied to CSV for review."""
	if not path:
		path = "logs/permission_denied.csv"
	p = Path(path)
	p.parent.mkdir(parents=True, exist_ok=True)
	with p.open("w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(["employee_id", "reason"])
		for emp_id in denied_users:
			writer.writerow([emp_id, "No permission to access user"])
	logger.info(f"Permission denied users CSV written: {p}")


@app.command()
def run(
	excel: str = typer.Argument(..., help="Path to Excel file with employee_id,pos_id columns"),
	config: str = typer.Option("config.yaml", help="Path to YAML config file"),
	env: Optional[str] = typer.Option(None, help="Path to .env file containing ADMIN_USERNAME and ADMIN_PASSWORD"),
	headful: bool = typer.Option(False, help="Run browser in headful mode for debugging"),
	dry_run: bool = typer.Option(False, help="Don't submit changes; just simulate"),
	offset: int = typer.Option(0, help="Start processing from this zero-based row index (after filtering)"),
	limit: Optional[int] = typer.Option(None, help="Maximum number of rows to process (after offset)"),
	retries: Optional[int] = typer.Option(None, help="Override retries per row"),
	retry_backoff_seconds: Optional[float] = typer.Option(None, help="Override retry backoff seconds"),
	log_file: Optional[str] = typer.Option(None, help="Path to write a rotating log file"),
	audit_csv: Optional[str] = typer.Option(None, help="Path to write audit CSV of changes"),
	invalid_csv: Optional[str] = typer.Option(None, help="Path to write CSV of users with missing POS data"),
	permission_denied_csv: Optional[str] = typer.Option(None, help="Path to write CSV of users with permission denied"),
	slowmo_ms: int = typer.Option(0, help="Slow down Playwright actions by N ms each"),
	step_delay_ms: int = typer.Option(0, help="Wait N ms between main steps (search/select/edit/save)"),
):
	"""Apply employee POS updates based on Excel file."""
	_setup_file_logging(log_file)
	valid_pairs, invalid_pairs = read_employee_pos_pairs(excel, offset=offset, limit=limit)
	logger.info(f"Loaded {len(valid_pairs)} valid pairs from {excel} (offset={offset}, limit={limit})")
	if invalid_pairs:
		logger.warning(f"Found {len(invalid_pairs)} users with missing POS data")
		_write_invalid_csv(invalid_csv, invalid_pairs)
	
	cfg = load_config(config)
	creds = load_credentials(env)

	results = asyncio.run(
		run_updates(
			cfg,
			creds,
			valid_pairs,
			headless=not headful,
			dry_run=dry_run,
			retries=retries,
			retry_backoff_seconds=retry_backoff_seconds,
			step_delay_ms=step_delay_ms,
			slowmo_ms=slowmo_ms,
		)
	)

	_write_audit_csv(audit_csv, results)
	
	# Separate permission denied users from other failures
	permission_denied_users = []
	other_failures = []
	
	for r in results:
		if not r.success:
			if "no permission" in str(r.error).lower() or "not found" in str(r.error).lower():
				permission_denied_users.append(r.employee_id)
			else:
				other_failures.append(r)
	
	# Write permission denied users to separate CSV
	if permission_denied_users:
		_write_permission_denied_csv(permission_denied_csv, permission_denied_users)
		logger.warning(f"Found {len(permission_denied_users)} users with permission denied")
	
	ok = sum(1 for r in results if r.success)
	fail = len(results) - ok
	logger.info(f"Done. Success: {ok}, Failed: {fail}")
	if fail:
		for r in results:
			if not r.success:
				logger.error(f"FAILED employee_id={r.employee_id}: {r.error}")


@app.command("run-pairs")
def run_pairs(
	pair: List[str] = typer.Option(..., help="One or more EMP=POS pairs"),
	config: str = typer.Option("config.yaml", help="Path to YAML config file"),
	env: Optional[str] = typer.Option(None, help="Path to .env file containing ADMIN_USERNAME and ADMIN_PASSWORD"),
	headful: bool = typer.Option(True, help="Run browser in headful mode for inspection"),
	dry_run: bool = typer.Option(False, help="Don't submit changes; just simulate"),
	retries: Optional[int] = typer.Option(None, help="Override retries per row"),
	retry_backoff_seconds: Optional[float] = typer.Option(None, help="Override retry backoff seconds"),
	log_file: Optional[str] = typer.Option(None, help="Path to write a rotating log file"),
	audit_csv: Optional[str] = typer.Option(None, help="Path to write audit CSV of changes"),
	slowmo_ms: int = typer.Option(0, help="Slow down Playwright actions by N ms each"),
	step_delay_ms: int = typer.Option(0, help="Wait N ms between main steps (search/select/edit/save)"),
):
	"""Run updates using manual EMP=POS pairs, no Excel required."""
	_setup_file_logging(log_file)
	pairs = _parse_pairs(pair)
	cfg = load_config(config)
	creds = load_credentials(env)

	results = asyncio.run(
		run_updates(
			cfg,
			creds,
			pairs,
			headless=not headful,
			dry_run=dry_run,
			retries=retries,
			retry_backoff_seconds=retry_backoff_seconds,
			step_delay_ms=step_delay_ms,
			slowmo_ms=slowmo_ms,
		)
	)

	_write_audit_csv(audit_csv, results)
	ok = sum(1 for r in results if r.success)
	fail = len(results) - ok
	logger.info(f"Done. Success: {ok}, Failed: {fail}")
	if fail:
		for r in results:
			if not r.success:
				logger.error(f"FAILED employee_id={r.employee_id}: {r.error}")


@app.command("test-login")
def test_login(
	config: str = typer.Option("config.yaml", help="Path to YAML config file"),
	env: Optional[str] = typer.Option(None, help="Path to .env file containing ADMIN_USERNAME and ADMIN_PASSWORD"),
	headful: bool = typer.Option(True, help="Run browser in headful mode for inspection"),
	wait_seconds: float = typer.Option(10.0, help="How many seconds to keep the browser open after login (headful only)"),
	keep_open: bool = typer.Option(False, help="Keep browser open longer (1 hour) for manual inspection"),
	slowmo_ms: int = typer.Option(0, help="Slow down Playwright actions by N ms each"),
):
	"""Open browser and try to login using config selectors and credentials."""
	cfg = load_config(config)
	creds = load_credentials(env)

	async def _run():
		async with async_playwright() as p:
			browser = await p.chromium.launch(headless=not headful, slow_mo=slowmo_ms if slowmo_ms > 0 else None)
			context = await browser.new_context()
			page = await context.new_page()
			try:
				logger.info("Navigating and attempting login...")
				await login(page, cfg, creds)
				logger.info("Login flow executed. Please verify the page shows you as logged in.")
				if headful:
					if keep_open:
						logger.info("Keeping browser open for 1 hour (use Ctrl+C to stop)...")
						await page.wait_for_timeout(60 * 60 * 1000)
					elif wait_seconds > 0:
						logger.info(f"Keeping browser open for {wait_seconds} seconds for manual verification...")
						await page.wait_for_timeout(int(wait_seconds * 1000))
			finally:
				await context.close()
				await browser.close()

	asyncio.run(_run())


if __name__ == "__main__":
	app()
