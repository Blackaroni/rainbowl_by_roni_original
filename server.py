from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from rainbowl_app.config import DatabaseConfig, ReminderEmailConfig, ServerConfig, parse_csv_list
from rainbowl_app.db import DatabaseAuditResult, DateRepairResult, ImportResult, Repository
from rainbowl_app.http import run_server
from rainbowl_app.reminders import dispatch_pending_order_reminders, start_reminder_loop


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SQL_PATH = BASE_DIR / "sql" / "postgres_rainbowl.sql"
CSV_DIR = BASE_DIR / "csv_files"


def build_parser() -> argparse.ArgumentParser:
    env_config = DatabaseConfig.from_env()
    reminder_config = ReminderEmailConfig.from_env()
    server_config = ServerConfig.from_env()
    parser = argparse.ArgumentParser(description="Rainbowl orders and sales app.")
    parser.add_argument("--db-host", default=env_config.host)
    parser.add_argument("--db-port", type=int, default=env_config.port)
    parser.add_argument("--db-name", default=env_config.name)
    parser.add_argument("--db-user", default=env_config.user)
    parser.add_argument("--db-password", default=env_config.password)
    parser.add_argument("--db-schema", default=env_config.schema)
    parser.add_argument("--db-sslmode", default=env_config.sslmode)
    parser.add_argument("--db-connect-timeout", type=int, default=env_config.connect_timeout)
    parser.add_argument("--smtp-host", default=reminder_config.smtp_host)
    parser.add_argument("--smtp-port", type=int, default=reminder_config.smtp_port)
    parser.add_argument("--smtp-user", default=reminder_config.smtp_user)
    parser.add_argument("--smtp-password", default=reminder_config.smtp_password)
    parser.add_argument("--smtp-sender", default=reminder_config.sender_email)
    parser.add_argument("--alert-recipient", default=reminder_config.recipient_email)
    parser.add_argument("--reminders-enabled", action="store_true", default=reminder_config.enabled)
    parser.add_argument("--reminder-interval-minutes", type=int, default=reminder_config.interval_minutes)
    parser.add_argument("--smtp-no-starttls", action="store_true", default=not reminder_config.use_starttls)

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-db", help="Apply the PostgreSQL schema.")

    import_parser = subparsers.add_parser("import", help="Import CSV exports from Google Sheets.")
    import_parser.add_argument("--customers", type=Path, help="Path to customers CSV export.")
    import_parser.add_argument("--products", type=Path, help="Path to products CSV export.")
    import_parser.add_argument("--sales", type=Path, help="Path to sales CSV export.")
    import_parser.add_argument("--expenses", type=Path, help="Path to expenses CSV export.")
    import_parser.add_argument("--accounts", type=Path, help="Path to accounts CSV export.")
    import_parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Truncate current data before importing.",
    )

    repair_parser = subparsers.add_parser(
        "repair-import-dates",
        help="Repair imported dates using the source CSV files.",
    )
    repair_parser.add_argument("--sales", type=Path, default=CSV_DIR / "sales.csv")
    repair_parser.add_argument("--expenses", type=Path, default=CSV_DIR / "expenses.csv")
    repair_parser.add_argument("--accounts", type=Path, default=CSV_DIR / "accounts.csv")

    serve_parser = subparsers.add_parser("serve", help="Start the web app.")
    serve_parser.add_argument("--host", default=server_config.host)
    serve_parser.add_argument("--port", type=int, default=server_config.port)
    serve_parser.add_argument(
        "--cors-allowed-origins",
        default=",".join(server_config.cors_allowed_origins),
        help="Comma-separated origins allowed to call the API from a different host.",
    )

    reminder_parser = subparsers.add_parser("send-reminders", help="Send pending-order reminder email.")
    reminder_parser.add_argument("--date", type=date.fromisoformat, help="Reminder run date in YYYY-MM-DD.")
    reminder_parser.add_argument("--dry-run", action="store_true", help="Print the reminder email instead of sending it.")

    audit_parser = subparsers.add_parser(
        "audit-db",
        help="Print row counts and financial totals for the current schema.",
    )
    audit_parser.add_argument("--json", action="store_true", help="Print audit data as JSON.")

    return parser


def build_database_config(args: argparse.Namespace) -> DatabaseConfig:
    return DatabaseConfig(
        host=args.db_host,
        port=args.db_port,
        name=args.db_name,
        user=args.db_user,
        password=args.db_password,
        schema=args.db_schema,
        sslmode=args.db_sslmode,
        connect_timeout=args.db_connect_timeout,
    )


def build_reminder_config(args: argparse.Namespace) -> ReminderEmailConfig:
    return ReminderEmailConfig(
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        smtp_user=args.smtp_user,
        smtp_password=args.smtp_password,
        sender_email=args.smtp_sender,
        recipient_email=args.alert_recipient,
        use_starttls=not args.smtp_no_starttls,
        enabled=args.reminders_enabled,
        interval_minutes=max(1, args.reminder_interval_minutes),
    )


def build_server_config(args: argparse.Namespace) -> ServerConfig:
    return ServerConfig(
        host=getattr(args, "host", "127.0.0.1"),
        port=int(getattr(args, "port", 8010)),
        cors_allowed_origins=parse_csv_list(getattr(args, "cors_allowed_origins", "")),
    )


def print_import_summary(result: ImportResult) -> None:
    print("Import completed:")
    print(f"  Customers: {result.customers}")
    print(f"  Products:  {result.products}")
    print(f"  Sales:     {result.sales}")
    print(f"  Expenses:  {result.expenses}")
    print(f"  Accounts:  {result.accounts}")


def print_date_repair_summary(result: DateRepairResult) -> None:
    print("Date repair completed:")
    print(f"  Sales orders updated:    {result.sales_orders}")
    print(f"  Sales payments updated:  {result.sales_payments}")
    print(f"  Expenses updated:        {result.expenses}")
    print(f"  Accounts updated:        {result.accounts}")


def print_reminder_summary(reminder_result) -> None:
    print("Reminder run completed:")
    print(f"  Reminder date:         {reminder_result.reminder_date}")
    print(f"  Orders needing alert:  {reminder_result.reminders_found}")
    print(f"  Emails sent:           {reminder_result.emails_sent}")
    print(f"  Notifications logged:  {reminder_result.notifications_logged}")
    print(f"  Dry run:               {reminder_result.dry_run}")


def print_database_audit_summary(result: DatabaseAuditResult) -> None:
    print("Database audit:")
    print(f"  Schema:                 {result.schema}")
    print(f"  Customers:              {result.customers}")
    print(f"  Products:               {result.products}")
    print(f"  Orders:                 {result.orders}")
    print(f"  Order items:            {result.order_items}")
    print(f"  Payments:               {result.payments}")
    print(f"  Expenses:               {result.expenses}")
    print(f"  Account snapshots:      {result.account_snapshots}")
    print(f"  Reminder notifications: {result.order_reminder_notifications}")
    print(f"  Sales total:            {result.sales_total:.2f}")
    print(f"  Paid total:             {result.paid_total:.2f}")
    print(f"  Expenses total:         {result.expenses_total:.2f}")
    print(f"  Outstanding total:      {result.outstanding_total:.2f}")
    print(f"  First order date:       {result.first_order_date or '-'}")
    print(f"  Last order date:        {result.last_order_date or '-'}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repository = Repository(build_database_config(args), SQL_PATH)
    reminder_config = build_reminder_config(args)
    server_config = build_server_config(args)

    if args.command == "init-db":
        repository.initialize()
        print(f"Schema applied to {args.db_name}.{args.db_schema}")
        return

    if args.command == "import":
        result = repository.import_csv_files(
            customers_path=args.customers,
            products_path=args.products,
            sales_path=args.sales,
            expenses_path=args.expenses,
            accounts_path=args.accounts,
            clear_existing=args.clear_existing,
        )
        print_import_summary(result)
        print(f"Database updated in {args.db_name}.{args.db_schema}")
        return

    if args.command == "repair-import-dates":
        result = repository.repair_imported_dates(
            sales_path=args.sales,
            expenses_path=args.expenses,
            accounts_path=args.accounts,
        )
        print_date_repair_summary(result)
        print(f"Database updated in {args.db_name}.{args.db_schema}")
        return

    if args.command == "send-reminders":
        repository.initialize()
        result = dispatch_pending_order_reminders(
            repository,
            reminder_config,
            reminder_date=args.date,
            dry_run=args.dry_run,
        )
        print_reminder_summary(result)
        return

    if args.command == "audit-db":
        result = repository.audit()
        if args.json:
            print(json.dumps(asdict(result), ensure_ascii=True, indent=2))
        else:
            print_database_audit_summary(result)
        return

    repository.initialize()
    if reminder_config.is_ready():
        start_reminder_loop(repository, reminder_config)
    elif reminder_config.enabled:
        print("Reminder loop not started because SMTP settings are incomplete.")
    run_server(
        repository,
        STATIC_DIR,
        server_config.host,
        server_config.port,
        allowed_origins=server_config.cors_allowed_origins,
    )


if __name__ == "__main__":
    main()
