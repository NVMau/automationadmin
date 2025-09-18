## Automation Admin – POS Update Automation

Automation tool to log in to the admin site, search by username (`sharing_key`), edit the correct record, update POS, and save with audit logs. Includes Excel ingestion, retries, slow motion for debugging, screenshots and CSV reports, and resume via offset/limit.

### Features
- Robust row selection by matching the table row containing exact `employee_id`
- Edit-form verification to prevent wrong-record updates
- Auto-accept save confirmation dialog
- Detailed rotating file logs and audit CSV
- Excel reader with Vietnamese header mapping, invalid POS detection
- Permission-denied detection with screenshots and CSV
- Slow motion (`--slowmo-ms`) and step delays (`--step-delay-ms`)
- Resume large runs using `--offset` and `--limit`

### Requirements
- Python 3.10+
- For `.xls` files: `xlrd>=2.0.1`

Install dependencies:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration
Copy and edit:
```bash
cp config.yaml.example config.yaml
```
Credentials via `.env`:
```dotenv
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
```

Important `config.yaml` fields: `login_url`, `employee_search_url`, selectors for username/password/login, and timeouts.

> Note: `.gitignore` excludes `config.yaml`, `logs/`, and `debug_*.png`.

### CLI

Login smoke test:
```bash
python -m automationadmin.cli test-login \
  --config config.yaml --env .env --headful \
  --slowmo-ms 300 --wait-seconds 10
```

Manual pairs:
```bash
python -m automationadmin.cli run-pairs \
  --config config.yaml --env .env --headful \
  --pair "C2C-084664=8LAN10002MFKHCK" \
  --pair "C2C-772802=8NTH10002MFKHCK" \
  --slowmo-ms 300 --step-delay-ms 800 \
  --log-file logs/run_pairs.log \
  --audit-csv logs/audit_pairs.csv
```

Excel-driven run:
```bash
python -m automationadmin.cli run ctkv8.xlsx \
  --config config.yaml --env .env \
  --headful --slowmo-ms 300 --step-delay-ms 800 \
  --log-file logs/run_excel.log \
  --audit-csv logs/audit_excel.csv \
  --invalid-csv logs/invalid_users.csv \
  --permission-denied-csv logs/permission_denied.csv
```

Resume (offset/limit after filtering valid rows):
```bash
python -m automationadmin.cli run ctkv8.xlsx \
  --config config.yaml --env .env \
  --offset 155 --limit 100 \
  --log-file logs/run_resume.log \
  --audit-csv logs/audit_resume.csv
```

### Excel Mapping
- `ma_msocial` → `employee_id`
- `ma_msocial_cap_tren` → `pos_id`
Rows with blank/`nan`/`#N/A` POS are written to `invalid_users.csv` and skipped.

### Outputs
- Logs: `logs/run_*.log`
- Audit: `employee_id,old_pos,new_pos,success,error`
- Invalid users: `employee_id,pos_id,reason`
- Permission denied: `employee_id,reason`
- Screenshots: `debug_*.png`

### Troubleshooting
- “Không có dữ liệu”: user missing or no permission → see `permission_denied.csv` and `debug_no_data_*.png`
- Timeouts: increase `timeouts` in `config.yaml`, or add `--retries`
- Slow page: use `--slowmo-ms` and `--step-delay-ms` to observe

### Project Layout
- `automationadmin/automation.py` – Playwright flow
- `automationadmin/excel_reader.py` – Excel reader (+ offset/limit)
- `automationadmin/cli.py` – Typer CLI

### License
MIT (update as needed)
