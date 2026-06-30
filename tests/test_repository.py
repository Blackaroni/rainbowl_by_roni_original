from __future__ import annotations

import unittest
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path

from rainbowl_app.config import DatabaseConfig
from rainbowl_app.db import Repository, calculate_line_financials, to_date_value


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base_config = DatabaseConfig.from_env()
        if not base_config.password:
            raise unittest.SkipTest("Database password is not set in .env or the current shell.")
        cls.schema = f"test_rainbowl_{uuid.uuid4().hex[:8]}"
        cls.repository = Repository(replace(base_config, schema=cls.schema))
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls) -> None:
        if not hasattr(cls, "repository"):
            return
        with cls.repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE')

    def setUp(self) -> None:
        self.repository.clear_existing_data()
        self.customer = self.repository.create_customer({"name": "Customer A"})
        self.product = self.repository.create_product(
            {
                "name": "Yogurt 2L",
                "selling_price": 20,
                "cost_price": 11,
            }
        )

    def test_margin_uses_discounted_total(self) -> None:
        result = calculate_line_financials(
            quantity=2,
            unit_price=20,
            unit_cost=11,
            discount_type="amount",
            discount_value=5,
        )
        self.assertEqual(result["line_subtotal"], 40)
        self.assertEqual(result["discount_amount"], 5)
        self.assertEqual(result["line_total"], 35)
        self.assertEqual(result["line_margin"], 13)

    def test_paid_but_pending_order_is_supported(self) -> None:
        order = self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "requested_collection_date": "2026-03-22",
                "fulfillment_status": "pending",
                "initial_payment": 20,
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )
        self.assertEqual(order["payment_status"], "paid")
        self.assertEqual(order["fulfillment_status"], "pending")
        dashboard = self.repository.dashboard()
        self.assertEqual(dashboard["total_sales"], 20)
        self.assertEqual(dashboard["total_paid"], 20)
        self.assertEqual(dashboard["total_outstanding"], 0)
        self.assertEqual(
            dashboard["total_sales"] - dashboard["total_paid"],
            dashboard["total_outstanding"],
        )

    def test_ambiguous_slash_dates_are_parsed_month_first(self) -> None:
        self.assertEqual(to_date_value("1/12/2026"), date(2026, 1, 12))
        self.assertEqual(to_date_value("03/08/2026"), date(2026, 3, 8))

    def test_customer_ids_increment_automatically(self) -> None:
        self.assertEqual(self.customer["legacy_customer_id"], "1")
        other_customer = self.repository.create_customer({"name": "Customer B"})
        self.assertEqual(other_customer["legacy_customer_id"], "2")

    def test_customer_can_be_updated(self) -> None:
        updated = self.repository.update_customer(
            self.customer["id"],
            {
                "name": "Customer A Updated",
                "phone_number": "08012345678",
                "location": "Lagos",
            },
        )
        self.assertEqual(updated["name"], "Customer A Updated")
        self.assertEqual(updated["phone_number"], "08012345678")
        self.assertEqual(updated["location"], "Lagos")

    def test_product_can_be_updated(self) -> None:
        updated = self.repository.update_product(
            self.product["id"],
            {
                "legacy_product_id": "TYZ-200",
                "name": "Yogurt 2L Deluxe",
                "selling_price": 25,
                "cost_price": 13,
            },
        )
        self.assertEqual(updated["legacy_product_id"], "TYZ-200")
        self.assertEqual(updated["name"], "Yogurt 2L Deluxe")
        self.assertEqual(updated["selling_price"], 25)
        self.assertEqual(updated["cost_price"], 13)

    def test_product_can_be_deleted_when_unreferenced(self) -> None:
        deleted = self.repository.delete_product(self.product["id"])
        self.assertEqual(deleted["id"], self.product["id"])
        with self.assertRaises(LookupError):
            self.repository.get_product(self.product["id"])

    def test_product_delete_is_blocked_when_linked_to_orders(self) -> None:
        self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "fulfillment_status": "pending",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "linked to 1 order item"):
            self.repository.delete_product(self.product["id"])

    def test_account_snapshots_include_order_payments(self) -> None:
        self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-15",
                "opening_balance": 10,
                "money_in": 5,
                "money_out": 2,
                "balance_in_bank": 3,
                "amount_in_account": 7,
            }
        )
        self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "fulfillment_status": "delivered",
                "initial_payment": 20,
                "payment_method": "cash",
                "payment_date": "2026-03-15",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )

        snapshot = next(
            row for row in self.repository.list_account_snapshots() if row["snapshot_date"] == "2026-03-15"
        )
        self.assertEqual(snapshot["manual_money_in"], 5)
        self.assertEqual(snapshot["payment_money_in"], 20)
        self.assertEqual(snapshot["money_in"], 25)
        self.assertEqual(snapshot["opening_balance"], 10)
        self.assertEqual(snapshot["balance"], 33)

    def test_account_snapshots_subtract_expenses_from_balance(self) -> None:
        self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-15",
                "opening_balance": 100,
            }
        )
        self.repository.create_expense(
            {
                "expense_date": "2026-03-15",
                "expense_category": "Supplies",
                "amount": 30,
                "description": "Packaging",
            }
        )

        snapshot = next(
            row for row in self.repository.list_account_snapshots() if row["snapshot_date"] == "2026-03-15"
        )
        self.assertEqual(snapshot["money_out"], 30)
        self.assertEqual(snapshot["expense_money_out"], 30)
        self.assertEqual(snapshot["balance"], 70)

    def test_account_snapshots_carry_forward_previous_balance(self) -> None:
        self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-15",
                "opening_balance": 100,
                "money_in": 20,
                "money_out": 10,
            }
        )
        self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-16",
                "money_in": 5,
                "money_out": 3,
            }
        )

        snapshots = {row["snapshot_date"]: row for row in self.repository.list_account_snapshots()}
        self.assertEqual(snapshots["2026-03-15"]["balance"], 110)
        self.assertEqual(snapshots["2026-03-16"]["opening_balance"], 110)
        self.assertEqual(snapshots["2026-03-16"]["balance"], 112)

    def test_imported_account_rows_only_provide_opening_baseline(self) -> None:
        first = self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-15",
                "opening_balance": 100,
                "money_in": 40,
                "money_out": 10,
            }
        )
        second = self.repository.create_account_snapshot(
            {
                "snapshot_date": "2026-03-16",
                "money_in": 30,
                "money_out": 5,
            }
        )
        with self.repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                        UPDATE {self.repository._table('account_snapshots')}
                        SET created_at = %s
                        WHERE id IN (%s, %s)
                    """,
                    ("2026-03-01T00:00:00+00:00", first["id"], second["id"]),
                )
        self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-16",
                "fulfillment_status": "delivered",
                "initial_payment": 20,
                "payment_method": "cash",
                "payment_date": "2026-03-16",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )
        self.repository.create_expense(
            {
                "expense_date": "2026-03-16",
                "expense_category": "Supplies",
                "amount": 5,
                "description": "Packaging",
            }
        )

        snapshots = {row["snapshot_date"]: row for row in self.repository.list_account_snapshots()}
        self.assertEqual(snapshots["2026-03-15"]["money_in"], 0)
        self.assertEqual(snapshots["2026-03-15"]["money_out"], 0)
        self.assertEqual(snapshots["2026-03-15"]["balance"], 100)
        self.assertEqual(snapshots["2026-03-16"]["opening_balance"], 100)
        self.assertEqual(snapshots["2026-03-16"]["payment_money_in"], 20)
        self.assertEqual(snapshots["2026-03-16"]["expense_money_out"], 5)
        self.assertEqual(snapshots["2026-03-16"]["balance"], 115)

    def test_monthly_insights_group_sales_expenses_and_cash_position(self) -> None:
        self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "fulfillment_status": "delivered",
                "initial_payment": 15,
                "payment_method": "transfer",
                "payment_date": "2026-03-15",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 2,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )
        self.repository.create_expense(
            {
                "expense_date": "2026-03-20",
                "expense_category": "Supplies",
                "amount": 5,
                "description": "Packaging",
            }
        )

        insights = self.repository.monthly_insights()
        month = next(row for row in insights["months"] if row["month"] == "2026-03")
        self.assertEqual(month["total_sales"], 40)
        self.assertEqual(month["total_paid"], 15)
        self.assertEqual(month["total_expenses"], 5)
        self.assertEqual(month["net_sales_after_expenses"], 35)
        self.assertEqual(month["cash_in_account"], 10)
        self.assertEqual(month["products"][0]["product_name"], "Yogurt 2L")
        self.assertEqual(month["products"][0]["quantity_sold"], 2)
        self.assertEqual(month["products"][0]["total_sales"], 40)

    def test_update_order_replaces_items_and_recalculates_totals(self) -> None:
        second_product = self.repository.create_product(
            {
                "name": "Yogurt 1L",
                "selling_price": 30,
                "cost_price": 12,
            }
        )
        order = self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "fulfillment_status": "processing",
                "initial_payment": 10,
                "payment_method": "transfer",
                "payment_date": "2026-03-15",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )

        updated = self.repository.update_order(
            order["id"],
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-16",
                "requested_collection_date": "2026-03-20",
                "fulfillment_status": "pending",
                "notes": "Corrected item",
                "items": [
                    {
                        "product_id": second_product["id"],
                        "quantity": 1,
                        "unit_price": 30,
                        "unit_cost": 12,
                        "discount_type": "amount",
                        "discount_value": 5,
                    }
                ],
            },
        )

        self.assertEqual(updated["order_date"], "2026-03-16")
        self.assertEqual(updated["requested_collection_date"], "2026-03-20")
        self.assertEqual(updated["fulfillment_status"], "pending")
        self.assertEqual(updated["notes"], "Corrected item")
        self.assertEqual(len(updated["items"]), 1)
        self.assertEqual(updated["items"][0]["product_id"], second_product["id"])
        self.assertEqual(updated["order_total"], 25)
        self.assertEqual(updated["amount_paid"], 10)
        self.assertEqual(updated["balance_due"], 15)
        self.assertEqual(updated["payment_status"], "partial")

    def test_due_order_reminders_are_listed_once_and_logged(self) -> None:
        order = self.repository.create_order(
            {
                "customer_id": self.customer["id"],
                "order_date": "2026-03-15",
                "requested_collection_date": "2026-03-18",
                "fulfillment_status": "pending",
                "items": [
                    {
                        "product_id": self.product["id"],
                        "quantity": 1,
                        "unit_price": 20,
                        "unit_cost": 11,
                        "discount_type": "none",
                        "discount_value": 0,
                    }
                ],
            }
        )

        reminders = self.repository.list_due_order_reminders(date(2026, 3, 16))
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["order_id"], order["id"])
        self.assertEqual(reminders[0]["days_before"], 2)

        logged = self.repository.record_order_reminder_notifications(
            reminders,
            recipient_email="alerts@rainbowl.example",
            reminder_date=date(2026, 3, 16),
            email_subject="Reminder",
        )
        self.assertEqual(logged, 1)
        self.assertEqual(self.repository.list_due_order_reminders(date(2026, 3, 16)), [])

    def test_sales_import_treats_sheet_prices_as_line_totals(self) -> None:
        self.repository.create_customer({"legacy_customer_id": "20", "name": "Import Customer"})
        self.repository.create_product(
            {
                "legacy_product_id": "005",
                "name": "Tigernut (50cl)",
                "selling_price": 2500,
                "cost_price": 1300,
            }
        )

        temp_dir = Path(__file__).resolve().parent / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        sales_path = temp_dir / f"sales_{uuid.uuid4().hex[:8]}.csv"
        try:
            sales_path.write_text(
                "\n".join(
                    [
                        "date,product_id,product_name,customer_id,quantity,cost_price,selling_price,Discount,margin",
                        "1/4/2026,005,Tigernut (50cl),20,2,\"1,300\",\"3,000\",,\"1,700\"",
                    ]
                ),
                encoding="utf-8",
            )
            result = self.repository.import_csv_files(sales_path=sales_path)
        finally:
            sales_path.unlink(missing_ok=True)

        self.assertEqual(result.sales, 1)
        orders = self.repository.list_orders()
        imported_order = next(order for order in orders if order["source"] == "sales_import")
        self.assertEqual(imported_order["order_total"], 3000)
        self.assertEqual(imported_order["margin_total"], 1700)
        self.assertEqual(imported_order["amount_paid"], 3000)
        self.assertEqual(imported_order["items"][0]["quantity"], 2)
        self.assertEqual(imported_order["items"][0]["unit_price"], 1500)
        self.assertEqual(imported_order["items"][0]["unit_cost"], 650)
        self.assertEqual(imported_order["items"][0]["line_total"], 3000)
        self.assertEqual(imported_order["items"][0]["line_margin"], 1700)

    def test_repair_imported_dates_restores_mm_dd_csv_dates(self) -> None:
        self.repository.create_customer({"legacy_customer_id": "20", "name": "Import Customer"})
        self.repository.create_product(
            {
                "legacy_product_id": "005",
                "name": "Tigernut (50cl)",
                "selling_price": 2500,
                "cost_price": 1300,
            }
        )

        temp_dir = Path(__file__).resolve().parent / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex[:8]
        sales_path = temp_dir / f"sales_{suffix}.csv"
        expenses_path = temp_dir / f"expenses_{suffix}.csv"
        accounts_path = temp_dir / f"accounts_{suffix}.csv"
        try:
            sales_path.write_text(
                "\n".join(
                    [
                        "date,product_id,product_name,customer_id,quantity,cost_price,selling_price,Discount,margin",
                        "1/12/2026,005,Tigernut (50cl),20,1,\"1,300\",\"2,500\",,\"1,200\"",
                    ]
                ),
                encoding="utf-8",
            )
            expenses_path.write_text(
                "\n".join(
                    [
                        "date,expense_category,product_id,description,quantity,uom,amount",
                        "1/10/2026,Ingredients,005,Culture,1,piece,\"3,500\"",
                    ]
                ),
                encoding="utf-8",
            )
            accounts_path.write_text(
                "\n".join(
                    [
                        "date,opening_balance,money_in,money_out,balance_in_bank,amount_in_account,difference",
                        "1/11/2026,\"100,000\",\"20,000\",\"5,000\",\"95,000\",\"115,000\",\"20,000\"",
                    ]
                ),
                encoding="utf-8",
            )
            result = self.repository.import_csv_files(
                sales_path=sales_path,
                expenses_path=expenses_path,
                accounts_path=accounts_path,
            )
            self.assertEqual(result.sales, 1)
            self.assertEqual(result.expenses, 1)
            self.assertEqual(result.accounts, 1)

            self.repository.create_expense(
                {
                    "expense_date": "2026-03-20",
                    "expense_category": "Packaging",
                    "amount": 500,
                    "description": "Manual row",
                }
            )

            with self.repository.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                            UPDATE {self.repository._table('orders')}
                            SET order_date = %s
                            WHERE source = 'sales_import'
                        """,
                        ("2026-12-01",),
                    )
                    cursor.execute(
                        f"""
                            UPDATE {self.repository._table('payments')}
                            SET payment_date = %s
                            WHERE notes = 'Imported payment'
                        """,
                        ("2026-12-01",),
                    )
                    cursor.execute(
                        f"""
                            UPDATE {self.repository._table('expenses')}
                            SET expense_date = %s
                            WHERE id = (
                                SELECT MIN(id)
                                FROM {self.repository._table('expenses')}
                            )
                        """,
                        ("2026-12-02",),
                    )
                    cursor.execute(
                        f"""
                            UPDATE {self.repository._table('account_snapshots')}
                            SET snapshot_date = %s
                            WHERE id = (
                                SELECT MIN(id)
                                FROM {self.repository._table('account_snapshots')}
                            )
                        """,
                        ("2026-12-03",),
                    )

            repair_result = self.repository.repair_imported_dates(
                sales_path=sales_path,
                expenses_path=expenses_path,
                accounts_path=accounts_path,
            )
        finally:
            sales_path.unlink(missing_ok=True)
            expenses_path.unlink(missing_ok=True)
            accounts_path.unlink(missing_ok=True)

        self.assertEqual(repair_result.sales_orders, 1)
        self.assertEqual(repair_result.sales_payments, 1)
        self.assertEqual(repair_result.expenses, 1)
        self.assertEqual(repair_result.accounts, 1)

        imported_order = next(order for order in self.repository.list_orders() if order["source"] == "sales_import")
        self.assertEqual(imported_order["order_date"], "2026-01-12")
        self.assertEqual(imported_order["payments"][0]["payment_date"], "2026-01-12")

        expenses = self.repository.list_expenses()
        imported_expense = next(expense for expense in expenses if expense["description"] == "Culture")
        manual_expense = next(expense for expense in expenses if expense["description"] == "Manual row")
        self.assertEqual(imported_expense["expense_date"], "2026-01-10")
        self.assertEqual(manual_expense["expense_date"], "2026-03-20")

        snapshot = next(
            row for row in self.repository.list_account_snapshots() if row["snapshot_date"] == "2026-01-11"
        )
        self.assertEqual(snapshot["snapshot_date"], "2026-01-11")


if __name__ == "__main__":
    unittest.main()
