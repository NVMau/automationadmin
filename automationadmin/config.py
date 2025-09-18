from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import os


class Timeouts(BaseModel):
	default: int = 15000
	navigation: int = 20000


class Selectors(BaseModel):
	username_input: str
	password_input: str
	login_submit: str
	search_input: str
	search_submit: str
	employee_row: str
	edit_button: str
	pos_input: str
	save_button: str


class AppConfig(BaseModel):
	base_url: str
	login_url: str
	employee_search_url: str
	selectors: Selectors
	timeouts: Timeouts = Field(default_factory=Timeouts)
	retries: int = 2
	retry_backoff_seconds: float = 2.0


@dataclass
class Credentials:
	username: str
	password: str


def load_config(config_path: str) -> AppConfig:
	with open(config_path, "r", encoding="utf-8") as f:
		data = yaml.safe_load(f) or {}
	return AppConfig(**data)


def load_credentials(env_path: Optional[str] = None) -> Credentials:
	# Load .env if provided or default .env in cwd
	load_dotenv(dotenv_path=env_path, override=False)
	username = os.getenv("ADMIN_USERNAME")
	password = os.getenv("ADMIN_PASSWORD")
	if not username or not password:
		raise ValueError("Missing ADMIN_USERNAME or ADMIN_PASSWORD in environment variables")
	return Credentials(username=username, password=password)
