from __future__ import annotations

from typing import Iterable, List, Tuple

import pandas as pd

REQUIRED_COLUMNS = ["employee_id", "pos_id"]


def read_employee_pos_pairs(xlsx_path: str, offset: int = 0, limit: int | None = None) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
	"""Read an Excel file and return valid pairs and invalid pairs.

	Returns:
		Tuple of (valid_pairs, invalid_pairs) where invalid_pairs are users with missing POS data.
	"""
	# Read sheet 0 by default, engine auto-detected by pandas/openpyxl
	df = pd.read_excel(xlsx_path)

	# Normalize column names to lowercase
	df.columns = [str(c).strip().lower() for c in df.columns]

	# Map Vietnamese column names to expected names (after lowercase normalization)
	# POS code nằm ở cột "tên điểm bán" theo file thực tế
	column_mapping = {
		"ma_msocial": "employee_id",
		# Optionally keep raw "thông tin điểm bán" if cần dùng sau
		"ma_msocial_cap_tren": "pos_id",
	}
	
	# Apply column mapping
	for vietnamese_name, english_name in column_mapping.items():
		if vietnamese_name in df.columns:
			df[english_name] = df[vietnamese_name]

	# Validate required columns
	missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
	if missing:
		raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

	valid_pairs: List[Tuple[str, str]] = []
	invalid_pairs: List[Tuple[str, str]] = []
	
	for _, row in df.iterrows():
		employee_id = str(row["employee_id"]).strip()
		pos_id = str(row["pos_id"]).strip()
		
		if not employee_id:
			continue
			
		# Check if POS data is missing or invalid
		if not pos_id or pos_id.lower() in ["#n/a", "nan", "none", ""]:
			invalid_pairs.append((employee_id, pos_id))
		else:
			valid_pairs.append((employee_id, pos_id))
	
	# Apply offset/limit to valid pairs (resume processing)
	start_index = max(int(offset or 0), 0)
	if limit is not None:
		end_index = start_index + int(limit)
		valid_pairs = valid_pairs[start_index:end_index]
	else:
		valid_pairs = valid_pairs[start_index:]

	return valid_pairs, invalid_pairs
