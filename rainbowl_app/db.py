from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from .config import DatabaseConfig


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
)

VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "postgres_rainbowl.sql"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_key(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def coerce_number(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return default
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()
    raw = raw.replace(",", "").replace("$", "")
    try:
        number = float(raw)
        return -number if negative else number
    except ValueError:
        return default


def normalize_date(value: Any) -> str:
    if value is None:
        return date.today().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if not raw:
        return date.today().isoformat()
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def to_date_value(value: Any) -> date:
    normalized = normalize_date(value)
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid date value: {value}") from exc


def to_optional_date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return to_date_value(value)


def to_datetime_value(value: Any, *, default: datetime | None = None) -> datetime | None:
    if value in (None, ""):
        return default
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return default
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed_date = to_date_value(raw)
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)


def parse_discount(value: Any) -> tuple[str, float]:
    if value is None:
        return "amount", 0.0
    raw = str(value).strip()
    if not raw:
        return "amount", 0.0
    if raw.endswith("%"):
        return "percent", float(coerce_number(raw[:-1], 0.0) or 0.0)
    return "amount", float(coerce_number(raw, 0.0) or 0.0)


def derive_payment_status(order_total: float, amount_paid: float) -> str:
    if amount_paid <= 0:
        return "unpaid"
    if amount_paid + 0.0001 >= order_total:
        return "paid"
    return "partial"


def calculate_line_financials(
    quantity: float,
    unit_price: float,
    unit_cost: float,
    discount_type: str,
    discount_value: float,
) -> dict[str, float]:
    subtotal = round(quantity * unit_price, 2)
    cost_total = round(quantity * unit_cost, 2)
    if discount_type == "percent":
        discount_amount = round(subtotal * (discount_value / 100), 2)
    elif discount_type == "amount":
        discount_amount = round(discount_value, 2)
    else:
        discount_amount = 0.0
    discount_amount = max(0.0, min(discount_amount, subtotal))
    line_total = round(subtotal - discount_amount, 2)
    line_margin = round(line_total - cost_total, 2)
    return {
        "discount_amount": discount_amount,
        "line_subtotal": subtotal,
        "line_total": line_total,
        "line_margin": line_margin,
    }


def clean_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_key(key): value for key, value in row.items()}


def serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    return value


def has_meaningful_value(value: Any) -> bool:
    return str(value or "").strip() not in {"", "None", "nan"}


def iter_csv_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers: list[str] | None = None
        for raw_row in reader:
            if not any(str(cell).strip() for cell in raw_row):
                continue
            headers = [str(cell) for cell in raw_row]
            break
        if headers is None:
            return rows
        header_count = len(headers)
        for raw_row in reader:
            if not any(str(cell).strip() for cell in raw_row):
                continue
            normalized_row = list(raw_row[:header_count])
            if len(normalized_row) < header_count:
                normalized_row.extend([""] * (header_count - len(normalized_row)))
            rows.append(clean_csv_row(dict(zip(headers, normalized_row, strict=False))))
    return rows


@dataclass
class ImportResult:
    customers: int = 0
    products: int = 0
    sales: int = 0
    expenses: int = 0
    accounts: int = 0


@dataclass
class DateRepairResult:
    sales_orders: int = 0
    sales_payments: int = 0
    expenses: int = 0
    accounts: int = 0


@dataclass
class DatabaseAuditResult:
    schema: str
    customers: int = 0
    products: int = 0
    orders: int = 0
    order_items: int = 0
    payments: int = 0
    expenses: int = 0
    account_snapshots: int = 0
    order_reminder_notifications: int = 0
    sales_total: float = 0.0
    paid_total: float = 0.0
    expenses_total: float = 0.0
    outstanding_total: float = 0.0
    first_order_date: str | None = None
    last_order_date: str | None = None


class Repository:
    def __init__(self, config: DatabaseConfig, sql_path: Path | None = None) -> None:
        if not VALID_IDENTIFIER.fullmatch(config.schema):
            raise ValueError("Schema name must be a valid SQL identifier.")
        self.config = config
        self.schema = config.schema
        self.sql_path = sql_path or DEFAULT_SQL_PATH

    def connect(self):
        return psycopg2.connect(**self.config.connection_kwargs())

    def initialize(self) -> None:
        sql_text = self.sql_path.read_text(encoding="utf-8")
        if self.schema != "rainbowl":
            sql_text = sql_text.replace("rainbowl", self.schema)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql_text)

    def audit(self) -> DatabaseAuditResult:
        table_names = (
            "customers",
            "products",
            "orders",
            "order_items",
            "payments",
            "expenses",
            "account_snapshots",
            "order_reminder_notifications",
        )
        with self.connect() as connection:
            counts = {
                table_name: self._count_rows(connection, table_name)
                for table_name in table_names
            }
            totals = self._fetchone(
                connection,
                f"""
                    SELECT
                        COALESCE(
                            (SELECT SUM(line_total) FROM {self._table('order_items')}),
                            0
                        ) AS sales_total,
                        COALESCE(
                            (SELECT SUM(amount) FROM {self._table('payments')}),
                            0
                        ) AS paid_total,
                        COALESCE(
                            (SELECT SUM(amount) FROM {self._table('expenses')}),
                            0
                        ) AS expenses_total,
                        COALESCE(
                            (
                                SELECT SUM(
                                    GREATEST(
                                        COALESCE(order_totals.order_total, 0) - COALESCE(payment_totals.amount_paid, 0),
                                        0
                                    )
                                )
                                FROM {self._table('orders')} AS orders
                                LEFT JOIN (
                                    SELECT order_id, SUM(line_total) AS order_total
                                    FROM {self._table('order_items')}
                                    GROUP BY order_id
                                ) AS order_totals ON order_totals.order_id = orders.id
                                LEFT JOIN (
                                    SELECT order_id, SUM(amount) AS amount_paid
                                    FROM {self._table('payments')}
                                    GROUP BY order_id
                                ) AS payment_totals ON payment_totals.order_id = orders.id
                            ),
                            0
                        ) AS outstanding_total,
                        (SELECT MIN(order_date) FROM {self._table('orders')}) AS first_order_date,
                        (SELECT MAX(order_date) FROM {self._table('orders')}) AS last_order_date
                """,
            )
        return DatabaseAuditResult(
            schema=self.schema,
            customers=counts["customers"],
            products=counts["products"],
            orders=counts["orders"],
            order_items=counts["order_items"],
            payments=counts["payments"],
            expenses=counts["expenses"],
            account_snapshots=counts["account_snapshots"],
            order_reminder_notifications=counts["order_reminder_notifications"],
            sales_total=float(totals["sales_total"] or 0.0),
            paid_total=float(totals["paid_total"] or 0.0),
            expenses_total=float(totals["expenses_total"] or 0.0),
            outstanding_total=float(totals["outstanding_total"] or 0.0),
            first_order_date=str(totals["first_order_date"]) if totals["first_order_date"] else None,
            last_order_date=str(totals["last_order_date"]) if totals["last_order_date"] else None,
        )

    def list_customers(self) -> list[dict[str, Any]]:
        query = f"""
            SELECT id, legacy_customer_id, name, phone_number, location, created_at, updated_at
            FROM {self._table('customers')}
            ORDER BY LOWER(name), id
        """
        with self.connect() as connection:
            return self._fetchall(connection, query)

    def next_customer_legacy_id(self) -> str:
        with self.connect() as connection:
            return self._next_customer_legacy_id(connection)

    def create_customer(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Customer name is required.")
        query = f"""
            INSERT INTO {self._table('customers')} (legacy_customer_id, name, phone_number, location)
            VALUES (%s, %s, %s, %s)
            RETURNING id, legacy_customer_id, name, phone_number, location, created_at, updated_at
        """
        with self.connect() as connection:
            legacy_customer_id = str(payload.get("legacy_customer_id", "")).strip() or self._next_customer_legacy_id(connection)
            existing = self._fetchone(
                connection,
                f"""
                    SELECT id
                    FROM {self._table('customers')}
                    WHERE legacy_customer_id = %s
                """,
                (legacy_customer_id,),
                required=False,
            )
            if existing is not None:
                raise ValueError(f"Customer ID {legacy_customer_id} already exists.")
            return self._fetchone(
                connection,
                query,
                (
                    legacy_customer_id,
                    name,
                    str(payload.get("phone_number", "")).strip() or None,
                    str(payload.get("location", "")).strip() or None,
                ),
            )

    def update_customer(self, customer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Customer name is required.")
        query = f"""
            UPDATE {self._table('customers')}
            SET name = %s, phone_number = %s, location = %s
            WHERE id = %s
            RETURNING id, legacy_customer_id, name, phone_number, location, created_at, updated_at
        """
        with self.connect() as connection:
            customer = self._fetchone(
                connection,
                query,
                (
                    name,
                    str(payload.get("phone_number", "")).strip() or None,
                    str(payload.get("location", "")).strip() or None,
                    customer_id,
                ),
                required=False,
            )
            if customer is None:
                raise LookupError("Customer not found.")
            return customer

    def list_products(self) -> list[dict[str, Any]]:
        query = f"""
            SELECT id, legacy_product_id, name, selling_price, cost_price, is_active, created_at, updated_at
            FROM {self._table('products')}
            ORDER BY LOWER(name), id
        """
        with self.connect() as connection:
            return self._fetchall(connection, query)

    def get_product(self, product_id: int) -> dict[str, Any]:
        query = f"""
            SELECT id, legacy_product_id, name, selling_price, cost_price, is_active, created_at, updated_at
            FROM {self._table('products')}
            WHERE id = %s
        """
        with self.connect() as connection:
            product = self._fetchone(connection, query, (product_id,), required=False)
        if product is None:
            raise LookupError("Product not found.")
        return product

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Product name is required.")
        query = f"""
            INSERT INTO {self._table('products')} (legacy_product_id, name, selling_price, cost_price, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            RETURNING id, legacy_product_id, name, selling_price, cost_price, is_active, created_at, updated_at
        """
        with self.connect() as connection:
            return self._fetchone(
                connection,
                query,
                (
                    str(payload.get("legacy_product_id", "")).strip() or None,
                    name,
                    float(coerce_number(payload.get("selling_price"), 0.0) or 0.0),
                    float(coerce_number(payload.get("cost_price"), 0.0) or 0.0),
                ),
            )

    def update_product(self, product_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Product name is required.")
        legacy_product_id = str(payload.get("legacy_product_id", "")).strip() or None
        query = f"""
            UPDATE {self._table('products')}
            SET legacy_product_id = %s, name = %s, selling_price = %s, cost_price = %s
            WHERE id = %s
            RETURNING id, legacy_product_id, name, selling_price, cost_price, is_active, created_at, updated_at
        """
        with self.connect() as connection:
            if not self._record_exists(connection, "products", product_id):
                raise LookupError("Product not found.")
            if legacy_product_id:
                existing = self._fetchone(
                    connection,
                    f"""
                        SELECT id
                        FROM {self._table('products')}
                        WHERE legacy_product_id = %s AND id <> %s
                    """,
                    (legacy_product_id, product_id),
                    required=False,
                )
                if existing is not None:
                    raise ValueError(f"Product ID {legacy_product_id} already exists.")
            product = self._fetchone(
                connection,
                query,
                (
                    legacy_product_id,
                    name,
                    float(coerce_number(payload.get("selling_price"), 0.0) or 0.0),
                    float(coerce_number(payload.get("cost_price"), 0.0) or 0.0),
                    product_id,
                ),
                required=False,
            )
        if product is None:
            raise LookupError("Product not found.")
        return product

    def delete_product(self, product_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            product = self._fetchone(
                connection,
                f"""
                    SELECT id, legacy_product_id, name, selling_price, cost_price, is_active, created_at, updated_at
                    FROM {self._table('products')}
                    WHERE id = %s
                """,
                (product_id,),
                required=False,
            )
            if product is None:
                raise LookupError("Product not found.")

            order_item_usage = self._fetchone(
                connection,
                f"SELECT COUNT(*) AS count FROM {self._table('order_items')} WHERE product_id = %s",
                (product_id,),
            )
            expense_usage = self._fetchone(
                connection,
                f"SELECT COUNT(*) AS count FROM {self._table('expenses')} WHERE product_id = %s",
                (product_id,),
            )

            references: list[str] = []
            order_item_count = int(order_item_usage["count"])
            expense_count = int(expense_usage["count"])
            if order_item_count:
                suffix = "" if order_item_count == 1 else "s"
                references.append(f"{order_item_count} order item{suffix}")
            if expense_count:
                suffix = "" if expense_count == 1 else "s"
                references.append(f"{expense_count} expense{suffix}")
            if references:
                raise ValueError(
                    "Product cannot be deleted because it is linked to "
                    + " and ".join(references)
                    + "."
                )

            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {self._table('products')} WHERE id = %s", (product_id,))
        return product

    def list_orders(self) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                orders.id,
                orders.order_number,
                orders.customer_id,
                customers.name AS customer_name,
                customers.phone_number AS customer_phone_number,
                orders.order_date,
                orders.requested_collection_date,
                orders.fulfilled_at,
                orders.payment_status,
                orders.fulfillment_status,
                orders.amount_paid,
                orders.notes,
                orders.source,
                orders.created_at,
                orders.updated_at
            FROM {self._table('orders')} AS orders
            JOIN {self._table('customers')} AS customers ON customers.id = orders.customer_id
            ORDER BY orders.order_date DESC, orders.id DESC
        """
        with self.connect() as connection:
            orders = self._fetchall(connection, query)
            order_ids = [order["id"] for order in orders]
            item_map = self._fetch_order_items_map(connection, order_ids)
            payment_map = self._fetch_payments_map(connection, order_ids)

        for order in orders:
            order["items"] = item_map.get(order["id"], [])
            order["payments"] = payment_map.get(order["id"], [])
            self._attach_order_totals(order)
        return orders

    def get_order(self, order_id: int) -> dict[str, Any]:
        query = f"""
            SELECT
                orders.id,
                orders.order_number,
                orders.customer_id,
                customers.name AS customer_name,
                customers.phone_number AS customer_phone_number,
                orders.order_date,
                orders.requested_collection_date,
                orders.fulfilled_at,
                orders.payment_status,
                orders.fulfillment_status,
                orders.amount_paid,
                orders.notes,
                orders.source,
                orders.created_at,
                orders.updated_at
            FROM {self._table('orders')} AS orders
            JOIN {self._table('customers')} AS customers ON customers.id = orders.customer_id
            WHERE orders.id = %s
        """
        with self.connect() as connection:
            order = self._fetchone(connection, query, (order_id,), required=False)
            if order is None:
                raise LookupError("Order not found.")
            order["items"] = self._fetch_order_items_map(connection, [order_id]).get(order_id, [])
            order["payments"] = self._fetch_payments_map(connection, [order_id]).get(order_id, [])
        self._attach_order_totals(order)
        return order

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        customer_id = int(payload.get("customer_id", 0))
        items = payload.get("items") or []
        if customer_id <= 0:
            raise ValueError("Customer is required.")
        if not isinstance(items, list) or not items:
            raise ValueError("At least one order item is required.")

        order_date = to_date_value(payload.get("order_date"))
        requested_collection_date = to_optional_date_value(payload.get("requested_collection_date"))
        fulfillment_status = str(payload.get("fulfillment_status", "pending")).strip() or "pending"
        if fulfillment_status not in {"pending", "processing", "ready", "delivered", "cancelled"}:
            raise ValueError("Invalid fulfillment status.")
        notes = str(payload.get("notes", "")).strip() or None
        source = str(payload.get("source", "app")).strip() or "app"
        initial_payment = float(coerce_number(payload.get("initial_payment"), 0.0) or 0.0)
        payment_method = str(payload.get("payment_method", "cash")).strip() or "cash"
        payment_date = to_date_value(payload.get("payment_date") or order_date)

        with self.connect() as connection:
            if not self._record_exists(connection, "customers", customer_id):
                raise ValueError("Customer does not exist.")

            order_id = self._insert_order_record(
                connection,
                order_number=self._generate_order_number(),
                customer_id=customer_id,
                order_date=order_date,
                requested_collection_date=requested_collection_date,
                fulfilled_at=to_datetime_value(payload.get("fulfilled_at") or order_date)
                if fulfillment_status == "delivered"
                else None,
                fulfillment_status=fulfillment_status,
                notes=notes,
                source=source,
            )
            for item in items:
                self._insert_order_item(connection, order_id, item)
            if initial_payment > 0:
                self._insert_payment(
                    connection,
                    order_id=order_id,
                    payment_date=payment_date,
                    amount=initial_payment,
                    method=payment_method,
                    notes="Initial payment",
                )
            self._refresh_order_payment_status(connection, order_id)
        return self.get_order(order_id)

    def update_order(self, order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        items = payload.get("items")
        updates: list[str] = []
        values: list[Any] = []
        if "customer_id" in payload:
            customer_id = int(payload.get("customer_id", 0))
            if customer_id <= 0:
                raise ValueError("Customer does not exist.")
            updates.append("customer_id = %s")
            values.append(customer_id)
        if "order_date" in payload:
            updates.append("order_date = %s")
            values.append(to_date_value(payload.get("order_date")))
        if "requested_collection_date" in payload:
            updates.append("requested_collection_date = %s")
            values.append(to_optional_date_value(payload.get("requested_collection_date")))
        if "fulfillment_status" in payload:
            fulfillment_status = str(payload.get("fulfillment_status", "")).strip()
            if fulfillment_status not in {"pending", "processing", "ready", "delivered", "cancelled"}:
                raise ValueError("Invalid fulfillment status.")
            updates.append("fulfillment_status = %s")
            values.append(fulfillment_status)
            updates.append("fulfilled_at = %s")
            values.append(
                to_datetime_value(payload.get("fulfilled_at"), default=now_utc())
                if fulfillment_status == "delivered"
                else None
            )
        if "notes" in payload:
            updates.append("notes = %s")
            values.append(str(payload.get("notes", "")).strip() or None)
        if items is not None:
            if not isinstance(items, list) or not items:
                raise ValueError("At least one order item is required.")
        if not updates and items is None:
            return self.get_order(order_id)

        with self.connect() as connection:
            if "customer_id" in payload and not self._record_exists(connection, "customers", int(payload.get("customer_id", 0))):
                raise ValueError("Customer does not exist.")
            if not self._record_exists(connection, "orders", order_id):
                raise LookupError("Order not found.")
            if updates:
                query = f"""
                    UPDATE {self._table('orders')}
                    SET {", ".join(updates)}
                    WHERE id = %s
                    RETURNING id
                """
                row = self._fetchone(connection, query, tuple(values + [order_id]), required=False)
                if row is None:
                    raise LookupError("Order not found.")
            if items is not None:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM {self._table('order_items')} WHERE order_id = %s",
                        (order_id,),
                    )
                for item in items:
                    self._insert_order_item(connection, order_id, item)
                self._refresh_order_payment_status(connection, order_id)
        return self.get_order(order_id)

    def add_payment(self, order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        amount = float(coerce_number(payload.get("amount"), 0.0) or 0.0)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        payment_date = to_date_value(payload.get("payment_date"))
        method = str(payload.get("method", "cash")).strip() or "cash"
        notes = str(payload.get("notes", "")).strip() or None
        with self.connect() as connection:
            if not self._record_exists(connection, "orders", order_id):
                raise LookupError("Order not found.")
            self._insert_payment(
                connection,
                order_id=order_id,
                payment_date=payment_date,
                amount=amount,
                method=method,
                notes=notes,
            )
            self._refresh_order_payment_status(connection, order_id)
        return self.get_order(order_id)

    def list_expenses(self) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                expenses.id,
                expenses.expense_date,
                expenses.expense_category,
                expenses.product_id,
                products.name AS product_name,
                expenses.description,
                expenses.quantity,
                expenses.uom,
                expenses.amount,
                expenses.created_at
            FROM {self._table('expenses')} AS expenses
            LEFT JOIN {self._table('products')} AS products ON products.id = expenses.product_id
            ORDER BY expenses.expense_date DESC, expenses.id DESC
        """
        with self.connect() as connection:
            return self._fetchall(connection, query)

    def create_expense(self, payload: dict[str, Any]) -> dict[str, Any]:
        expense_category = str(payload.get("expense_category", "")).strip()
        if not expense_category:
            raise ValueError("Expense category is required.")
        query = f"""
            INSERT INTO {self._table('expenses')} (
                expense_date,
                expense_category,
                product_id,
                description,
                quantity,
                uom,
                amount
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                expense_date,
                expense_category,
                product_id,
                description,
                quantity,
                uom,
                amount,
                created_at
        """
        with self.connect() as connection:
            expense = self._fetchone(
                connection,
                query,
                (
                    to_date_value(payload.get("expense_date")),
                    expense_category,
                    int(payload.get("product_id")) if payload.get("product_id") not in (None, "", 0, "0") else None,
                    str(payload.get("description", "")).strip() or None,
                    coerce_number(payload.get("quantity"), None),
                    str(payload.get("uom", "")).strip() or None,
                    float(coerce_number(payload.get("amount"), 0.0) or 0.0),
                ),
            )
            expense["product_name"] = (
                self._fetch_product_name(connection, int(expense["product_id"]))
                if expense["product_id"]
                else None
            )
        return expense

    def list_account_snapshots(self) -> list[dict[str, Any]]:
        snapshot_query = f"""
            SELECT
                id,
                snapshot_date,
                opening_balance,
                money_in,
                money_out,
                balance_in_bank,
                amount_in_account,
                difference,
                created_at
            FROM {self._table('account_snapshots')}
            ORDER BY snapshot_date ASC, id ASC
        """
        payment_query = f"""
            SELECT
                payment_date AS snapshot_date,
                COALESCE(SUM(amount), 0) AS payment_money_in
            FROM {self._table('payments')}
            GROUP BY payment_date
        """
        expense_query = f"""
            SELECT
                expense_date AS snapshot_date,
                COALESCE(SUM(amount), 0) AS expense_money_out
            FROM {self._table('expenses')}
            GROUP BY expense_date
        """
        with self.connect() as connection:
            snapshots = self._fetchall(connection, snapshot_query)
            payment_rows = self._fetchall(connection, payment_query)
            expense_rows = self._fetchall(connection, expense_query)

        imported_batch_created_at = self._detect_imported_account_batch_created_at(snapshots)
        imported_snapshot_dates = {
            str(row["snapshot_date"])
            for row in snapshots
            if self._is_imported_account_snapshot(row, imported_batch_created_at)
        }
        manual_snapshot_map = self._group_manual_account_snapshots_by_date(
            snapshots,
            imported_batch_created_at=imported_batch_created_at,
        )
        opening_snapshot = self._find_opening_account_snapshot(snapshots)
        payment_map = {
            str(row["snapshot_date"]): round(float(row["payment_money_in"]), 2)
            for row in payment_rows
        }
        expense_map = {
            str(row["snapshot_date"]): round(float(row["expense_money_out"]), 2)
            for row in expense_rows
        }
        all_dates = sorted(
            imported_snapshot_dates
            | set(manual_snapshot_map)
            | set(payment_map)
            | set(expense_map)
            | ({str(opening_snapshot["snapshot_date"])} if opening_snapshot is not None else set())
        )

        merged_rows: list[dict[str, Any]] = []
        running_balance = 0.0
        has_running_balance = False

        for snapshot_date in all_dates:
            manual_row = manual_snapshot_map.get(snapshot_date)
            opening_override = None
            if manual_row is not None:
                opening_override_value = float(manual_row.get("opening_balance", 0.0) or 0.0)
                if opening_override_value != 0.0:
                    opening_override = round(opening_override_value, 2)
            if opening_override is not None:
                opening_balance = opening_override
            elif not has_running_balance and opening_snapshot is not None:
                opening_balance = round(float(opening_snapshot["opening_balance"]), 2)
            elif has_running_balance:
                opening_balance = round(running_balance, 2)
            else:
                opening_balance = 0.0

            manual_money_in = round(float((manual_row or {}).get("money_in", 0.0) or 0.0), 2)
            manual_money_out = round(float((manual_row or {}).get("money_out", 0.0) or 0.0), 2)
            payment_money_in = payment_map.get(snapshot_date, 0.0)
            expense_money_out = expense_map.get(snapshot_date, 0.0)
            money_in = round(payment_money_in + manual_money_in, 2)
            money_out = round(expense_money_out + manual_money_out, 2)
            balance = round(opening_balance + money_in - money_out, 2)

            merged_row = self._build_account_snapshot_row(
                snapshot_date=snapshot_date,
                opening_balance=opening_balance,
                money_in=money_in,
                money_out=money_out,
                balance=balance,
                raw_opening_balance=opening_override,
                manual_money_in=manual_money_in,
                manual_money_out=manual_money_out,
                payment_money_in=payment_money_in,
                expense_money_out=expense_money_out,
                id_value=(manual_row or {}).get("id"),
                created_at=(manual_row or {}).get("created_at"),
            )
            merged_rows.append(merged_row)
            running_balance = balance
            has_running_balance = True

        merged_rows.sort(
            key=lambda row: (str(row["snapshot_date"]), int(row["id"] or 0)),
            reverse=True,
        )
        return merged_rows

    def create_account_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        opening_balance = float(coerce_number(payload.get("opening_balance"), 0.0) or 0.0)
        money_in = float(coerce_number(payload.get("money_in"), 0.0) or 0.0)
        money_out = float(coerce_number(payload.get("money_out"), 0.0) or 0.0)
        computed_balance = round(opening_balance + money_in - money_out, 2)
        query = f"""
            INSERT INTO {self._table('account_snapshots')} (
                snapshot_date,
                opening_balance,
                money_in,
                money_out,
                balance_in_bank,
                amount_in_account,
                difference
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                snapshot_date,
                opening_balance,
                money_in,
                money_out,
                balance_in_bank,
                amount_in_account,
                difference,
                created_at
        """
        with self.connect() as connection:
            return self._fetchone(
                connection,
                query,
                (
                    to_date_value(payload.get("snapshot_date")),
                    opening_balance,
                    money_in,
                    money_out,
                    computed_balance,
                    computed_balance,
                    0.0,
                ),
            )

    def list_sales_lines(self) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                date,
                product_id,
                product_name,
                customer_id,
                customer_name,
                quantity,
                cost_price,
                selling_price,
                discount,
                margin,
                payment_status,
                fulfillment_status
            FROM {self._table('sales_lines')}
            ORDER BY date DESC
        """
        with self.connect() as connection:
            return self._fetchall(connection, query)

    def dashboard(self) -> dict[str, Any]:
        orders = self.list_orders()
        total_sales = round(
            sum(order["order_total"] for order in orders if order["fulfillment_status"] != "cancelled"),
            2,
        )
        total_paid = round(
            sum(float(order["amount_paid"]) for order in orders if order["fulfillment_status"] != "cancelled"),
            2,
        )
        total_outstanding = round(sum(order["balance_due"] for order in orders if order["fulfillment_status"] != "cancelled"), 2)
        pending_orders = sum(1 for order in orders if order["fulfillment_status"] in {"pending", "processing", "ready"})
        delivered_unpaid = sum(
            1
            for order in orders
            if order["fulfillment_status"] == "delivered" and order["payment_status"] != "paid"
        )
        return {
            "total_sales": total_sales,
            "total_paid": total_paid,
            "total_outstanding": total_outstanding,
            "pending_orders": pending_orders,
            "delivered_unpaid": delivered_unpaid,
            "order_count": len(orders),
        }

    def monthly_insights(self) -> dict[str, Any]:
        sales_query = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', orders.order_date), 'YYYY-MM') AS month,
                COALESCE(SUM(order_items.line_total), 0) AS total_sales,
                COALESCE(SUM(order_items.line_margin), 0) AS gross_profit
            FROM {self._table('orders')} AS orders
            JOIN {self._table('order_items')} AS order_items ON order_items.order_id = orders.id
            WHERE orders.fulfillment_status <> 'cancelled'
            GROUP BY DATE_TRUNC('month', orders.order_date)
        """
        payment_query = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', payment_date), 'YYYY-MM') AS month,
                COALESCE(SUM(amount), 0) AS total_paid
            FROM {self._table('payments')}
            GROUP BY DATE_TRUNC('month', payment_date)
        """
        expense_query = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', expense_date), 'YYYY-MM') AS month,
                COALESCE(SUM(amount), 0) AS total_expenses,
                COALESCE(
                    SUM(
                        CASE
                            WHEN LOWER(TRIM(expense_category)) IN (
                                'investment',
                                'investments',
                                'regulatory',
                                'equipment',
                                'machinery',
                                'business cost',
                                'business costs',
                                'businesscost',
                                'businesscosts'
                            )
                            THEN 0
                            ELSE amount
                        END
                    ),
                    0
                ) AS profit_expenses
            FROM {self._table('expenses')}
            GROUP BY DATE_TRUNC('month', expense_date)
        """
        product_query = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', orders.order_date), 'YYYY-MM') AS month,
                products.name AS product_name,
                COALESCE(SUM(order_items.quantity), 0) AS quantity_sold,
                COALESCE(SUM(order_items.quantity * order_items.unit_cost), 0) AS total_cost,
                COALESCE(SUM(order_items.line_total), 0) AS total_sales,
                COALESCE(SUM(order_items.line_margin), 0) AS total_margin
            FROM {self._table('orders')} AS orders
            JOIN {self._table('order_items')} AS order_items ON order_items.order_id = orders.id
            JOIN {self._table('products')} AS products ON products.id = order_items.product_id
            WHERE orders.fulfillment_status <> 'cancelled'
            GROUP BY DATE_TRUNC('month', orders.order_date), products.name
            ORDER BY DATE_TRUNC('month', orders.order_date) DESC, SUM(order_items.line_total) DESC, LOWER(products.name)
        """
        with self.connect() as connection:
            sales_rows = self._fetchall(connection, sales_query)
            payment_rows = self._fetchall(connection, payment_query)
            expense_rows = self._fetchall(connection, expense_query)
            product_rows = self._fetchall(connection, product_query)

        months: dict[str, dict[str, Any]] = {}

        def ensure_month(month_key: str) -> dict[str, Any]:
            if month_key not in months:
                months[month_key] = {
                    "month": month_key,
                    "total_sales": 0.0,
                    "gross_profit": 0.0,
                    "total_paid": 0.0,
                    "total_expenses": 0.0,
                    "profit_expenses": 0.0,
                    "net_sales_after_expenses": 0.0,
                    "net_profit_after_expenses": 0.0,
                    "cash_in_account": 0.0,
                    "products": [],
                }
            return months[month_key]

        for row in sales_rows:
            month = str(row["month"])
            month_row = ensure_month(month)
            month_row["total_sales"] = round(float(row["total_sales"]), 2)
            month_row["gross_profit"] = round(float(row["gross_profit"]), 2)

        for row in payment_rows:
            month = str(row["month"])
            ensure_month(month)["total_paid"] = round(float(row["total_paid"]), 2)

        for row in expense_rows:
            month = str(row["month"])
            month_row = ensure_month(month)
            month_row["total_expenses"] = round(float(row["total_expenses"]), 2)
            month_row["profit_expenses"] = round(float(row["profit_expenses"]), 2)

        for row in product_rows:
            month = str(row["month"])
            ensure_month(month)["products"].append(
                {
                    "product_name": str(row["product_name"]),
                    "quantity_sold": round(float(row["quantity_sold"]), 3),
                    "total_cost": round(float(row["total_cost"]), 2),
                    "total_sales": round(float(row["total_sales"]), 2),
                    "total_margin": round(float(row["total_margin"]), 2),
                }
            )

        month_rows = sorted(months.values(), key=lambda row: row["month"], reverse=True)
        for month in month_rows:
            month["products"].sort(key=lambda row: row["total_sales"], reverse=True)
            month["net_sales_after_expenses"] = round(month["total_sales"] - month["total_expenses"], 2)
            month["net_profit_after_expenses"] = round(month["gross_profit"] - month["profit_expenses"], 2)
            month["cash_in_account"] = round(month["total_paid"] - month["total_expenses"], 2)

        return {"months": month_rows}

    def list_due_order_reminders(self, reminder_date: date | None = None) -> list[dict[str, Any]]:
        reminder_date = reminder_date or date.today()
        one_day_date = reminder_date + timedelta(days=1)
        two_days_date = reminder_date + timedelta(days=2)
        query = f"""
            SELECT
                orders.id AS order_id,
                orders.order_number,
                orders.requested_collection_date,
                orders.fulfillment_status,
                orders.payment_status,
                orders.amount_paid,
                customers.name AS customer_name,
                customers.phone_number AS customer_phone_number,
                customers.location AS customer_location,
                COALESCE(SUM(order_items.line_total), 0) AS order_total,
                CASE
                    WHEN orders.requested_collection_date = %s THEN 1
                    WHEN orders.requested_collection_date = %s THEN 2
                END AS days_before
            FROM {self._table('orders')} AS orders
            JOIN {self._table('customers')} AS customers ON customers.id = orders.customer_id
            LEFT JOIN {self._table('order_items')} AS order_items ON order_items.order_id = orders.id
            WHERE orders.requested_collection_date IN (%s, %s)
              AND orders.fulfillment_status IN ('pending', 'processing', 'ready')
              AND NOT EXISTS (
                  SELECT 1
                  FROM {self._table('order_reminder_notifications')} AS reminders
                  WHERE reminders.order_id = orders.id
                    AND reminders.reminder_date = %s
                    AND reminders.days_before = CASE
                        WHEN orders.requested_collection_date = %s THEN 1
                        WHEN orders.requested_collection_date = %s THEN 2
                    END
              )
            GROUP BY
                orders.id,
                orders.order_number,
                orders.requested_collection_date,
                orders.fulfillment_status,
                orders.payment_status,
                orders.amount_paid,
                customers.name,
                customers.phone_number,
                customers.location
            ORDER BY orders.requested_collection_date ASC, LOWER(customers.name), orders.id
        """
        with self.connect() as connection:
            reminders = self._fetchall(
                connection,
                query,
                (
                    one_day_date,
                    two_days_date,
                    one_day_date,
                    two_days_date,
                    reminder_date,
                    one_day_date,
                    two_days_date,
                ),
            )
        for reminder in reminders:
            order_total = round(float(reminder["order_total"]), 2)
            amount_paid = round(float(reminder["amount_paid"]), 2)
            reminder["balance_due"] = round(max(0.0, order_total - amount_paid), 2)
            reminder["order_total"] = order_total
            reminder["amount_paid"] = amount_paid
            reminder["reminder_date"] = reminder_date.isoformat()
        return reminders

    def record_order_reminder_notifications(
        self,
        reminders: list[dict[str, Any]],
        *,
        recipient_email: str,
        reminder_date: date | None = None,
        email_subject: str | None = None,
    ) -> int:
        if not reminders:
            return 0
        reminder_date = reminder_date or date.today()
        query = f"""
            INSERT INTO {self._table('order_reminder_notifications')} (
                order_id,
                reminder_date,
                days_before,
                recipient_email,
                email_subject
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (order_id, reminder_date, days_before) DO NOTHING
        """
        inserted = 0
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for reminder in reminders:
                    cursor.execute(
                        query,
                        (
                            int(reminder["order_id"]),
                            reminder_date,
                            int(reminder["days_before"]),
                            recipient_email,
                            email_subject,
                        ),
                    )
                    inserted += cursor.rowcount
        return inserted

    def import_csv_files(
        self,
        *,
        customers_path: Path | None = None,
        products_path: Path | None = None,
        sales_path: Path | None = None,
        expenses_path: Path | None = None,
        accounts_path: Path | None = None,
        clear_existing: bool = False,
    ) -> ImportResult:
        result = ImportResult()
        self.initialize()
        if clear_existing:
            self.clear_existing_data()
        if customers_path:
            result.customers = self._import_customers(customers_path)
        if products_path:
            result.products = self._import_products(products_path)
        if sales_path:
            result.sales = self._import_sales(sales_path)
        if expenses_path:
            result.expenses = self._import_expenses(expenses_path)
        if accounts_path:
            result.accounts = self._import_accounts(accounts_path)
        return result

    def repair_imported_dates(
        self,
        *,
        sales_path: Path | None = None,
        expenses_path: Path | None = None,
        accounts_path: Path | None = None,
    ) -> DateRepairResult:
        result = DateRepairResult()
        self.initialize()
        with self.connect() as connection:
            if sales_path:
                sales_rows = self._collect_sales_date_repairs(sales_path)
                result.sales_orders, result.sales_payments = self._repair_sales_import_dates(
                    connection,
                    sales_rows,
                )
            if expenses_path:
                expense_dates = self._collect_expense_date_repairs(expenses_path)
                result.expenses = self._repair_expense_dates(connection, expense_dates)
            if accounts_path:
                account_dates = self._collect_account_date_repairs(accounts_path)
                result.accounts = self._repair_account_snapshot_dates(connection, account_dates)
        return result

    def clear_existing_data(self) -> None:
        query = f"""
            TRUNCATE TABLE
                {self._table('order_reminder_notifications')},
                {self._table('payments')},
                {self._table('order_items')},
                {self._table('orders')},
                {self._table('expenses')},
                {self._table('account_snapshots')},
                {self._table('customers')},
                {self._table('products')}
            RESTART IDENTITY CASCADE
        """
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)

    def _fetch_order_items_map(
        self,
        connection,
        order_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not order_ids:
            return {}
        query = f"""
            SELECT
                order_items.id,
                order_items.order_id,
                order_items.product_id,
                products.name AS product_name,
                order_items.quantity,
                order_items.unit_cost,
                order_items.unit_price,
                order_items.discount_type,
                order_items.discount_value,
                order_items.discount_amount,
                order_items.line_subtotal,
                order_items.line_total,
                order_items.line_margin,
                order_items.notes
            FROM {self._table('order_items')} AS order_items
            JOIN {self._table('products')} AS products ON products.id = order_items.product_id
            WHERE order_items.order_id = ANY(%s)
            ORDER BY order_items.id
        """
        rows = self._fetchall(connection, query, (order_ids,))
        item_map: dict[int, list[dict[str, Any]]] = {order_id: [] for order_id in order_ids}
        for row in rows:
            item_map[int(row["order_id"])].append(row)
        return item_map

    def _fetch_payments_map(
        self,
        connection,
        order_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not order_ids:
            return {}
        query = f"""
            SELECT id, order_id, payment_date, amount, method, notes, created_at
            FROM {self._table('payments')}
            WHERE order_id = ANY(%s)
            ORDER BY payment_date DESC, id DESC
        """
        rows = self._fetchall(connection, query, (order_ids,))
        payment_map: dict[int, list[dict[str, Any]]] = {order_id: [] for order_id in order_ids}
        for row in rows:
            payment_map[int(row["order_id"])].append(row)
        return payment_map

    def _attach_order_totals(self, order: dict[str, Any]) -> None:
        order_total = round(sum(float(item["line_total"]) for item in order["items"]), 2)
        subtotal = round(sum(float(item["line_subtotal"]) for item in order["items"]), 2)
        discount_total = round(sum(float(item["discount_amount"]) for item in order["items"]), 2)
        margin_total = round(sum(float(item["line_margin"]) for item in order["items"]), 2)
        balance_due = round(max(0.0, order_total - float(order["amount_paid"])), 2)
        order["subtotal"] = subtotal
        order["discount_total"] = discount_total
        order["order_total"] = order_total
        order["margin_total"] = margin_total
        order["balance_due"] = balance_due

    def _insert_order_item(
        self,
        connection,
        order_id: int,
        payload: dict[str, Any],
    ) -> None:
        product_id = int(payload.get("product_id", 0))
        if product_id <= 0:
            raise ValueError("Each order item must have a product.")
        product = self._fetchone(
            connection,
            f"""
                SELECT id, selling_price, cost_price
                FROM {self._table('products')}
                WHERE id = %s
            """,
            (product_id,),
            required=False,
        )
        if product is None:
            raise ValueError(f"Product {product_id} does not exist.")
        quantity = float(coerce_number(payload.get("quantity"), 0.0) or 0.0)
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        unit_price = float(coerce_number(payload.get("unit_price"), product["selling_price"]) or 0.0)
        unit_cost = float(coerce_number(payload.get("unit_cost"), product["cost_price"]) or 0.0)
        discount_type = str(payload.get("discount_type", "amount")).strip() or "amount"
        if discount_type not in {"none", "amount", "percent"}:
            raise ValueError("Invalid discount type.")
        discount_value = float(coerce_number(payload.get("discount_value"), 0.0) or 0.0)
        financials = calculate_line_financials(quantity, unit_price, unit_cost, discount_type, discount_value)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                    INSERT INTO {self._table('order_items')} (
                        order_id,
                        product_id,
                        quantity,
                        unit_cost,
                        unit_price,
                        discount_type,
                        discount_value,
                        discount_amount,
                        line_subtotal,
                        line_total,
                        line_margin,
                        notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    product_id,
                    quantity,
                    unit_cost,
                    unit_price,
                    discount_type,
                    discount_value,
                    financials["discount_amount"],
                    financials["line_subtotal"],
                    financials["line_total"],
                    financials["line_margin"],
                    str(payload.get("notes", "")).strip() or None,
                ),
            )

    def _refresh_order_payment_status(self, connection, order_id: int) -> None:
        total_row = self._fetchone(
            connection,
            f"""
                SELECT COALESCE(SUM(line_total), 0) AS order_total
                FROM {self._table('order_items')}
                WHERE order_id = %s
            """,
            (order_id,),
        )
        payment_row = self._fetchone(
            connection,
            f"""
                SELECT COALESCE(SUM(amount), 0) AS amount_paid
                FROM {self._table('payments')}
                WHERE order_id = %s
            """,
            (order_id,),
        )
        order_total = float(total_row["order_total"])
        amount_paid = float(payment_row["amount_paid"])
        payment_status = derive_payment_status(order_total, amount_paid)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                    UPDATE {self._table('orders')}
                    SET amount_paid = %s, payment_status = %s
                    WHERE id = %s
                """,
                (amount_paid, payment_status, order_id),
            )

    def _generate_order_number(self) -> str:
        return f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    def _next_customer_legacy_id(self, connection) -> str:
        row = self._fetchone(
            connection,
            f"""
                SELECT COALESCE(MAX((legacy_customer_id)::INTEGER), 0) + 1 AS next_id
                FROM {self._table('customers')}
                WHERE legacy_customer_id ~ '^[0-9]+$'
            """,
        )
        return str(int(row["next_id"]))

    def _import_customers(self, path: Path) -> int:
        count = 0
        query = f"""
            INSERT INTO {self._table('customers')} (legacy_customer_id, name, phone_number, location)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (legacy_customer_id) DO UPDATE SET
                name = EXCLUDED.name,
                phone_number = EXCLUDED.phone_number,
                location = EXCLUDED.location
        """
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for row in iter_csv_rows(path):
                    name = str(row.get("customer_name", "")).strip()
                    if not name:
                        continue
                    cursor.execute(
                        query,
                        (
                            str(row.get("customer_id", "")).strip() or None,
                            name,
                            str(row.get("phone_number", "")).strip() or None,
                            str(row.get("location", "")).strip() or None,
                        ),
                    )
                    count += 1
        return count

    def _import_products(self, path: Path) -> int:
        count = 0
        query = f"""
            INSERT INTO {self._table('products')} (legacy_product_id, name, selling_price, cost_price, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (legacy_product_id) DO UPDATE SET
                name = EXCLUDED.name,
                selling_price = EXCLUDED.selling_price,
                cost_price = EXCLUDED.cost_price
        """
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for row in iter_csv_rows(path):
                    name = str(row.get("product_name", "")).strip()
                    if not name:
                        continue
                    cursor.execute(
                        query,
                        (
                            str(row.get("product_id", "")).strip() or None,
                            name,
                            float(coerce_number(row.get("selling_price"), 0.0) or 0.0),
                            float(coerce_number(row.get("cost_price"), 0.0) or 0.0),
                        ),
                    )
                    count += 1
        return count

    def _import_sales(self, path: Path) -> int:
        count = 0
        with self.connect() as connection:
            for row in iter_csv_rows(path):
                if not any(
                    has_meaningful_value(row.get(key))
                    for key in ("date", "product_id", "product_name", "customer_id", "customer_name", "quantity")
                ):
                    continue
                quantity = float(coerce_number(row.get("quantity"), 0.0) or 0.0)
                if quantity <= 0:
                    continue
                customer_id = self._resolve_customer_for_import(connection, row)

                normalized_row = dict(row)
                raw_selling_total = (
                    float(coerce_number(row.get("selling_price"), 0.0) or 0.0)
                    if has_meaningful_value(row.get("selling_price"))
                    else None
                )
                raw_cost_total = (
                    float(coerce_number(row.get("cost_price"), 0.0) or 0.0)
                    if has_meaningful_value(row.get("cost_price"))
                    else None
                )
                if raw_selling_total is not None:
                    normalized_row["selling_price"] = round(raw_selling_total / quantity, 2)
                if raw_cost_total is not None:
                    normalized_row["cost_price"] = round(raw_cost_total / quantity, 2)

                product_id = self._resolve_product_for_import(connection, normalized_row)

                product_row = self._fetchone(
                    connection,
                    f"""
                        SELECT selling_price, cost_price
                        FROM {self._table('products')}
                        WHERE id = %s
                    """,
                    (product_id,),
                )
                unit_price = (
                    round(raw_selling_total / quantity, 2)
                    if raw_selling_total is not None
                    else float(coerce_number(product_row["selling_price"], 0.0) or 0.0)
                )
                unit_cost = (
                    round(raw_cost_total / quantity, 2)
                    if raw_cost_total is not None
                    else float(coerce_number(product_row["cost_price"], 0.0) or 0.0)
                )
                discount_note = str(row.get("discount", "")).strip()
                item_note = None
                if discount_note:
                    item_note = (
                        "Imported discount note: "
                        f"{discount_note}. Sales sheet prices were treated as final line totals."
                    )
                order_payload = {
                    "customer_id": customer_id,
                    "order_date": row.get("date"),
                    "requested_collection_date": row.get("requested_collection_date"),
                    "fulfillment_status": str(row.get("fulfillment_status", "delivered")).strip() or "delivered",
                    "notes": str(row.get("description", "")).strip() or "Imported from sales sheet",
                    "source": "sales_import",
                    "payment_method": str(row.get("payment_method", "legacy")).strip() or "legacy",
                    "payment_date": row.get("payment_date") or row.get("date"),
                    "items": [
                        {
                            "product_id": product_id,
                            "quantity": quantity,
                            "unit_cost": unit_cost,
                            "unit_price": unit_price,
                            "discount_type": "none",
                            "discount_value": 0.0,
                            "notes": item_note,
                        }
                    ],
                }
                item_financials = calculate_line_financials(
                    quantity,
                    unit_price,
                    unit_cost,
                    "none",
                    0.0,
                )
                amount_paid = float(coerce_number(row.get("amount_paid"), 0.0) or 0.0)
                if amount_paid <= 0:
                    payment_status = str(row.get("payment_status", "paid")).strip() or "paid"
                    amount_paid = item_financials["line_total"] if payment_status == "paid" else 0.0
                order_payload["initial_payment"] = amount_paid
                self._create_order_in_connection(connection, order_payload)
                count += 1
        return count

    def _import_expenses(self, path: Path) -> int:
        count = 0
        query = f"""
            INSERT INTO {self._table('expenses')} (
                expense_date,
                expense_category,
                product_id,
                description,
                quantity,
                uom,
                amount
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for row in iter_csv_rows(path):
                    if not any(
                        has_meaningful_value(row.get(key))
                        for key in ("date", "expense_category", "product_id", "description", "quantity", "amount")
                    ):
                        continue
                    cursor.execute(
                        query,
                        (
                            to_date_value(row.get("date")),
                            str(row.get("expense_category", "")).strip() or "General",
                            self._find_product_id_by_legacy_id(connection, row.get("product_id")),
                            str(row.get("description", "")).strip() or None,
                            coerce_number(row.get("quantity"), None),
                            str(row.get("uom", "")).strip() or None,
                            float(coerce_number(row.get("amount"), 0.0) or 0.0),
                        ),
                    )
                    count += 1
        return count

    def _import_accounts(self, path: Path) -> int:
        count = 0
        query = f"""
            INSERT INTO {self._table('account_snapshots')} (
                snapshot_date,
                opening_balance,
                money_in,
                money_out,
                balance_in_bank,
                amount_in_account,
                difference
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for row in iter_csv_rows(path):
                    relevant_keys = (
                        "opening_balance",
                        "money_in",
                        "money_out",
                        "balance_in_bank",
                        "amount_in_account",
                        "difference",
                    )
                    if not has_meaningful_value(row.get("date")) and not any(
                        has_meaningful_value(row.get(key)) for key in relevant_keys
                    ):
                        continue
                    try:
                        snapshot_date = to_date_value(row.get("date"))
                    except ValueError:
                        if not any(has_meaningful_value(row.get(key)) for key in relevant_keys):
                            continue
                        raise
                    balance_in_bank = float(coerce_number(row.get("balance_in_bank"), 0.0) or 0.0)
                    amount_in_account = float(coerce_number(row.get("amount_in_account"), 0.0) or 0.0)
                    cursor.execute(
                        query,
                        (
                            snapshot_date,
                            float(coerce_number(row.get("opening_balance"), 0.0) or 0.0),
                            float(coerce_number(row.get("money_in"), 0.0) or 0.0),
                            float(coerce_number(row.get("money_out"), 0.0) or 0.0),
                            balance_in_bank,
                            amount_in_account,
                            float(
                                coerce_number(
                                    row.get("difference"),
                                    round(amount_in_account - balance_in_bank, 2),
                                )
                                or 0.0
                            ),
                        ),
                    )
                    count += 1
        return count

    def _collect_sales_date_repairs(self, path: Path) -> list[dict[str, date | None]]:
        rows: list[dict[str, date | None]] = []
        for row in iter_csv_rows(path):
            if not any(
                has_meaningful_value(row.get(key))
                for key in ("date", "product_id", "product_name", "customer_id", "customer_name", "quantity")
            ):
                continue
            quantity = float(coerce_number(row.get("quantity"), 0.0) or 0.0)
            if quantity <= 0:
                continue
            payment_status = str(row.get("payment_status", "paid")).strip() or "paid"
            amount_paid = float(coerce_number(row.get("amount_paid"), 0.0) or 0.0)
            has_imported_payment = amount_paid > 0 or payment_status == "paid"
            rows.append(
                {
                    "order_date": to_date_value(row.get("date")),
                    "requested_collection_date": to_optional_date_value(row.get("requested_collection_date")),
                    "payment_date": to_date_value(row.get("payment_date") or row.get("date"))
                    if has_imported_payment
                    else None,
                }
            )
        return rows

    def _collect_expense_date_repairs(self, path: Path) -> list[date]:
        rows: list[date] = []
        for row in iter_csv_rows(path):
            if not any(
                has_meaningful_value(row.get(key))
                for key in ("date", "expense_category", "product_id", "description", "quantity", "amount")
            ):
                continue
            rows.append(to_date_value(row.get("date")))
        return rows

    def _collect_account_date_repairs(self, path: Path) -> list[date]:
        rows: list[date] = []
        for row in iter_csv_rows(path):
            relevant_keys = (
                "opening_balance",
                "money_in",
                "money_out",
                "balance_in_bank",
                "amount_in_account",
                "difference",
            )
            if not has_meaningful_value(row.get("date")) and not any(
                has_meaningful_value(row.get(key)) for key in relevant_keys
            ):
                continue
            try:
                rows.append(to_date_value(row.get("date")))
            except ValueError:
                if any(has_meaningful_value(row.get(key)) for key in relevant_keys):
                    raise
        return rows

    def _repair_sales_import_dates(
        self,
        connection,
        rows: list[dict[str, date | None]],
    ) -> tuple[int, int]:
        if not rows:
            return 0, 0
        order_rows = self._fetchall(
            connection,
            f"""
                SELECT id, fulfillment_status
                FROM {self._table('orders')}
                WHERE source = 'sales_import'
                ORDER BY created_at, id
            """,
        )
        if len(order_rows) != len(rows):
            raise ValueError(
                f"Sales repair expected {len(rows)} imported orders, found {len(order_rows)}."
            )

        payment_count = 0
        with connection.cursor() as cursor:
            for order_row, repair_row in zip(order_rows, rows, strict=True):
                order_id = int(order_row["id"])
                fulfilled_at = (
                    datetime.combine(repair_row["order_date"], time.min, tzinfo=timezone.utc)
                    if order_row["fulfillment_status"] == "delivered"
                    else None
                )
                cursor.execute(
                    f"""
                        UPDATE {self._table('orders')}
                        SET order_date = %s,
                            requested_collection_date = %s,
                            fulfilled_at = %s
                        WHERE id = %s
                    """,
                    (
                        repair_row["order_date"],
                        repair_row["requested_collection_date"],
                        fulfilled_at,
                        order_id,
                    ),
                )
                payment_rows = self._fetchall(
                    connection,
                    f"""
                        SELECT id
                        FROM {self._table('payments')}
                        WHERE order_id = %s
                          AND notes = 'Imported payment'
                        ORDER BY created_at, id
                    """,
                    (order_id,),
                )
                if repair_row["payment_date"] is None:
                    if payment_rows:
                        raise ValueError(
                            f"Sales repair found an unexpected imported payment for order {order_id}."
                        )
                    continue
                if len(payment_rows) != 1:
                    raise ValueError(
                        f"Sales repair expected 1 imported payment for order {order_id}, found {len(payment_rows)}."
                    )
                cursor.execute(
                    f"""
                        UPDATE {self._table('payments')}
                        SET payment_date = %s
                        WHERE id = %s
                    """,
                    (
                        repair_row["payment_date"],
                        int(payment_rows[0]["id"]),
                    ),
                )
                payment_count += 1
        return len(order_rows), payment_count

    def _repair_expense_dates(self, connection, rows: list[date]) -> int:
        if not rows:
            return 0
        expense_ids = self._select_earliest_created_batch_ids(connection, "expenses", len(rows))
        with connection.cursor() as cursor:
            for expense_id, expense_date in zip(expense_ids, rows, strict=True):
                cursor.execute(
                    f"""
                        UPDATE {self._table('expenses')}
                        SET expense_date = %s
                        WHERE id = %s
                    """,
                    (expense_date, expense_id),
                )
        return len(expense_ids)

    def _repair_account_snapshot_dates(self, connection, rows: list[date]) -> int:
        if not rows:
            return 0
        snapshot_ids = self._select_earliest_created_batch_ids(connection, "account_snapshots", len(rows))
        with connection.cursor() as cursor:
            for snapshot_id, snapshot_date in zip(snapshot_ids, rows, strict=True):
                cursor.execute(
                    f"""
                        UPDATE {self._table('account_snapshots')}
                        SET snapshot_date = %s
                        WHERE id = %s
                    """,
                    (snapshot_date, snapshot_id),
                )
        return len(snapshot_ids)

    def _select_earliest_created_batch_ids(
        self,
        connection,
        table_name: str,
        expected_count: int,
    ) -> list[int]:
        batch_row = self._fetchone(
            connection,
            f"""
                SELECT created_at, COUNT(*) AS row_count
                FROM {self._table(table_name)}
                GROUP BY created_at
                ORDER BY created_at ASC
                LIMIT 1
            """,
            required=False,
        )
        if batch_row is None:
            raise ValueError(f"No rows found in {table_name} to repair.")
        row_count = int(batch_row["row_count"])
        if row_count != expected_count:
            raise ValueError(
                f"{table_name} repair expected the earliest import batch to contain "
                f"{expected_count} rows, found {row_count}."
            )
        rows = self._fetchall(
            connection,
            f"""
                SELECT id
                FROM {self._table(table_name)}
                WHERE created_at = %s
                ORDER BY id
            """,
            (batch_row["created_at"],),
        )
        return [int(row["id"]) for row in rows]

    def _resolve_customer_for_import(self, connection, row: dict[str, Any]) -> int:
        legacy_customer_id = str(row.get("customer_id", "")).strip()
        if legacy_customer_id:
            existing = self._fetchone(
                connection,
                f"""
                    SELECT id
                    FROM {self._table('customers')}
                    WHERE legacy_customer_id = %s
                """,
                (legacy_customer_id,),
                required=False,
            )
            if existing is not None:
                return int(existing["id"])
        name = str(row.get("customer_name", "")).strip() or f"Customer {legacy_customer_id or uuid.uuid4().hex[:6]}"
        existing_by_name = self._fetchone(
            connection,
            f"""
                SELECT id
                FROM {self._table('customers')}
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
            """,
            (name,),
            required=False,
        )
        if existing_by_name is not None:
            return int(existing_by_name["id"])
        return int(
            self._fetchone(
                connection,
                f"""
                    INSERT INTO {self._table('customers')} (legacy_customer_id, name, phone_number, location)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """,
                (
                    legacy_customer_id or None,
                    name,
                    str(row.get("phone_number", "")).strip() or None,
                    str(row.get("location", "")).strip() or None,
                ),
            )["id"]
        )

    def _resolve_product_for_import(self, connection, row: dict[str, Any]) -> int:
        legacy_product_id = str(row.get("product_id", "")).strip()
        product_name = str(row.get("product_name", "")).strip()
        existing_id = self._find_product_id_by_legacy_id(connection, legacy_product_id)
        if existing_id is not None:
            return existing_id
        if product_name:
            existing = self._fetchone(
                connection,
                f"""
                    SELECT id
                    FROM {self._table('products')}
                    WHERE LOWER(name) = LOWER(%s)
                    LIMIT 1
                """,
                (product_name,),
                required=False,
            )
            if existing is not None:
                return int(existing["id"])
        return int(
            self._fetchone(
                connection,
                f"""
                    INSERT INTO {self._table('products')} (legacy_product_id, name, selling_price, cost_price, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                    RETURNING id
                """,
                (
                    legacy_product_id or None,
                    product_name or f"Product {legacy_product_id or uuid.uuid4().hex[:6]}",
                    float(coerce_number(row.get("selling_price"), 0.0) or 0.0),
                    float(coerce_number(row.get("cost_price"), 0.0) or 0.0),
                ),
            )["id"]
        )

    def _find_product_id_by_legacy_id(self, connection, legacy_product_id: Any) -> int | None:
        raw = str(legacy_product_id or "").strip()
        if not raw:
            return None
        row = self._fetchone(
            connection,
            f"""
                SELECT id
                FROM {self._table('products')}
                WHERE legacy_product_id = %s
            """,
            (raw,),
            required=False,
        )
        return int(row["id"]) if row is not None else None

    def _create_order_in_connection(self, connection, payload: dict[str, Any]) -> int:
        customer_id = int(payload.get("customer_id", 0))
        if customer_id <= 0:
            raise ValueError("Customer is required.")
        items = payload.get("items") or []
        if not items:
            raise ValueError("At least one order item is required.")
        order_date = to_date_value(payload.get("order_date"))
        requested_collection_date = to_optional_date_value(payload.get("requested_collection_date"))
        fulfillment_status = str(payload.get("fulfillment_status", "pending")).strip() or "pending"
        order_id = self._insert_order_record(
            connection,
            order_number=self._generate_order_number(),
            customer_id=customer_id,
            order_date=order_date,
            requested_collection_date=requested_collection_date,
            fulfilled_at=to_datetime_value(payload.get("fulfilled_at") or order_date)
            if fulfillment_status == "delivered"
            else None,
            fulfillment_status=fulfillment_status,
            notes=str(payload.get("notes", "")).strip() or None,
            source=str(payload.get("source", "app")).strip() or "app",
        )
        for item in items:
            self._insert_order_item(connection, order_id, item)
        initial_payment = float(coerce_number(payload.get("initial_payment"), 0.0) or 0.0)
        if initial_payment > 0:
            self._insert_payment(
                connection,
                order_id=order_id,
                payment_date=to_date_value(payload.get("payment_date") or order_date),
                amount=initial_payment,
                method=str(payload.get("payment_method", "cash")).strip() or "cash",
                notes="Imported payment" if payload.get("source") != "app" else "Initial payment",
            )
        self._refresh_order_payment_status(connection, order_id)
        return order_id

    def _insert_order_record(
        self,
        connection,
        *,
        order_number: str,
        customer_id: int,
        order_date: date,
        requested_collection_date: date | None,
        fulfilled_at: datetime | None,
        fulfillment_status: str,
        notes: str | None,
        source: str,
    ) -> int:
        query = f"""
            INSERT INTO {self._table('orders')} (
                order_number,
                customer_id,
                order_date,
                requested_collection_date,
                fulfilled_at,
                payment_status,
                fulfillment_status,
                amount_paid,
                notes,
                source
            ) VALUES (%s, %s, %s, %s, %s, 'unpaid', %s, 0, %s, %s)
            RETURNING id
        """
        return int(
            self._fetchone(
                connection,
                query,
                (
                    order_number,
                    customer_id,
                    order_date,
                    requested_collection_date,
                    fulfilled_at,
                    fulfillment_status,
                    notes,
                    source,
                ),
            )["id"]
        )

    def _insert_payment(
        self,
        connection,
        *,
        order_id: int,
        payment_date: date,
        amount: float,
        method: str,
        notes: str | None,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                    INSERT INTO {self._table('payments')} (order_id, payment_date, amount, method, notes)
                    VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, payment_date, amount, method, notes),
            )

    def _detect_imported_account_batch_created_at(self, snapshots: list[dict[str, Any]]) -> str | None:
        counts: dict[str, int] = {}
        for snapshot in snapshots:
            created_at = str(snapshot.get("created_at") or "")
            if not created_at:
                continue
            counts[created_at] = counts.get(created_at, 0) + 1
        imported_batches = [created_at for created_at, count in counts.items() if count > 1]
        return min(imported_batches) if imported_batches else None

    def _is_imported_account_snapshot(
        self,
        snapshot: dict[str, Any],
        imported_batch_created_at: str | None,
    ) -> bool:
        return (
            imported_batch_created_at is not None
            and str(snapshot.get("created_at") or "") == imported_batch_created_at
        )

    def _group_manual_account_snapshots_by_date(
        self,
        snapshots: list[dict[str, Any]],
        *,
        imported_batch_created_at: str | None,
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for snapshot in snapshots:
            if self._is_imported_account_snapshot(snapshot, imported_batch_created_at):
                continue
            snapshot_date = str(snapshot["snapshot_date"])
            current_id = int(snapshot["id"]) if snapshot.get("id") is not None else 0
            entry = grouped.setdefault(
                snapshot_date,
                {
                    "id": snapshot.get("id"),
                    "snapshot_date": snapshot_date,
                    "opening_balance": 0.0,
                    "money_in": 0.0,
                    "money_out": 0.0,
                    "created_at": snapshot.get("created_at"),
                },
            )
            entry["money_in"] = round(
                float(entry["money_in"]) + float(snapshot.get("money_in", 0.0) or 0.0),
                2,
            )
            entry["money_out"] = round(
                float(entry["money_out"]) + float(snapshot.get("money_out", 0.0) or 0.0),
                2,
            )
            opening_balance = round(float(snapshot.get("opening_balance", 0.0) or 0.0), 2)
            if opening_balance != 0.0:
                entry["opening_balance"] = opening_balance
            existing_id = int(entry["id"]) if entry.get("id") is not None else 0
            if current_id >= existing_id:
                entry["id"] = snapshot.get("id")
                entry["created_at"] = snapshot.get("created_at")
        return grouped

    def _find_opening_account_snapshot(self, snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
        for snapshot in snapshots:
            if round(float(snapshot.get("opening_balance", 0.0) or 0.0), 2) != 0.0:
                return snapshot
        return snapshots[0] if snapshots else None

    def _build_account_snapshot_row(
        self,
        *,
        snapshot_date: str,
        opening_balance: float,
        money_in: float,
        money_out: float,
        balance: float,
        raw_opening_balance: float | None,
        manual_money_in: float,
        manual_money_out: float,
        payment_money_in: float,
        expense_money_out: float,
        id_value: Any,
        created_at: Any,
    ) -> dict[str, Any]:
        return {
            "id": id_value,
            "snapshot_date": snapshot_date,
            "opening_balance": round(opening_balance, 2),
            "money_in": round(money_in, 2),
            "money_out": round(money_out, 2),
            "balance": round(balance, 2),
            "balance_in_bank": round(balance, 2),
            "amount_in_account": round(balance, 2),
            "difference": 0.0,
            "created_at": created_at,
            "raw_opening_balance": round(float(raw_opening_balance or 0.0), 2),
            "manual_money_in": round(manual_money_in, 2),
            "manual_money_out": round(manual_money_out, 2),
            "payment_money_in": round(payment_money_in, 2),
            "expense_money_out": round(expense_money_out, 2),
        }

    def _fetch_product_name(self, connection, product_id: int) -> str | None:
        row = self._fetchone(
            connection,
            f"SELECT name FROM {self._table('products')} WHERE id = %s",
            (product_id,),
            required=False,
        )
        return str(row["name"]) if row is not None else None

    def _record_exists(self, connection, table_name: str, record_id: int) -> bool:
        row = self._fetchone(
            connection,
            f"SELECT id FROM {self._table(table_name)} WHERE id = %s",
            (record_id,),
            required=False,
        )
        return row is not None

    def _count_rows(self, connection, table_name: str) -> int:
        row = self._fetchone(
            connection,
            f"SELECT COUNT(*) AS count FROM {self._table(table_name)}",
        )
        return int(row["count"])

    def _fetchall(self, connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [self._serialize_row(row) for row in cursor.fetchall()]

    def _fetchone(
        self,
        connection,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        required: bool = True,
    ) -> dict[str, Any] | None:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
        if row is None:
            if required:
                raise LookupError("Record not found.")
            return None
        return self._serialize_row(row)

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: serialize_value(value) for key, value in row.items()}

    def _table(self, name: str) -> str:
        if not VALID_IDENTIFIER.fullmatch(name):
            raise ValueError("Table name must be a valid SQL identifier.")
        return f'"{self.schema}"."{name}"'
