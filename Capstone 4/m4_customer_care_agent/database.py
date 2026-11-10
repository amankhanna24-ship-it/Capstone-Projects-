"""
database.py - NovaShop's pretend company database (SQLite).

SQLite is a whole database in one file (novashop.db). No server to install.
Run `python database.py` to (re)create it with fresh sample data.

Dates are set RELATIVE TO TODAY, so the refund windows in the demo always
behave the same way whichever day you run it.
"""

import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.getenv("NOVASHOP_DB", "novashop.db")

SCHEMA = """
DROP TABLE IF EXISTS customers;  DROP TABLE IF EXISTS products;  DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS order_items; DROP TABLE IF EXISTS shipments; DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS escalations;

CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, email TEXT, tier TEXT);
CREATE TABLE products  (sku TEXT PRIMARY KEY, name TEXT, colour TEXT, price REAL, stock INTEGER, restock_date TEXT);
CREATE TABLE orders    (order_id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, total REAL,
                        currency TEXT, placed_at TEXT, delivered_at TEXT);
CREATE TABLE order_items (order_id TEXT, sku TEXT, qty INTEGER, unit_price REAL);
CREATE TABLE shipments (order_id TEXT PRIMARY KEY, carrier TEXT, tracking_no TEXT, status TEXT,
                        last_location TEXT, eta TEXT, updated_at TEXT);
CREATE TABLE refunds   (refund_id TEXT PRIMARY KEY, order_id TEXT, amount REAL, reason TEXT,
                        status TEXT, created_at TEXT, note TEXT);
CREATE TABLE escalations (ticket_id TEXT PRIMARY KEY, customer_id TEXT, order_id TEXT, reason TEXT,
                          summary TEXT, priority TEXT, created_at TEXT);
"""


def _d(days: float) -> str:
    """A date `days` from now (negative = in the past), as ISO text."""
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def seed(path: str = DB_PATH) -> str:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)

    con.executemany("INSERT INTO customers VALUES (?,?,?,?)", [
        ("CUST-0001", "Priya Sharma", "priya@example.com", "standard"),
        ("CUST-0002", "James Wilson", "james@example.com", "gold"),
        ("CUST-0003", "Ananya Rao", "ananya@example.com", "standard"),
    ])

    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", [
        ("SKU-HDP200", "Wireless Headphones H200", "black", 129.99, 14, None),
        ("SKU-KTL01B", "Electric Kettle 1.7L",    "blue",   39.50,  0, _d(6)[:10]),
        ("SKU-KTL01W", "Electric Kettle 1.7L",    "white",  39.50, 22, None),
        ("SKU-MUG4ST", "Stoneware Mug Set (4)",   "grey",   24.00, 40, None),
        ("SKU-LMP300", "Desk Lamp L300",          "brass",  45.50,  8, None),
        ("SKU-JKT900", "Rain Jacket R900",        "navy",   89.00,  5, None),
    ])

    #           order_id    customer     status       total   placed  delivered
    orders = [("NS-10001", "CUST-0001", "SHIPPED",    129.99, _d(-3),  None),     # scenario 1: in transit
              ("NS-10002", "CUST-0001", "DELIVERED",   24.00, _d(-8),  _d(-3)),   # scenario 2
              ("NS-10003", "CUST-0001", "PROCESSING",  39.50, _d(-1),  None),     # scenario 2
              ("NS-10004", "CUST-0002", "DELIVERED",  129.99, _d(-9),  _d(-5)),   # scenario 3: damaged
              ("NS-10005", "CUST-0003", "PROCESSING",  45.50, _d(-1),  None),     # scenario 4: cancel
              ("NS-10006", "CUST-0002", "DELIVERED",   89.00, _d(-50), _d(-45))]  # scenario 5: too old
    con.executemany("INSERT INTO orders VALUES (?,?,?,?, 'GBP', ?,?)", orders)

    con.executemany("INSERT INTO order_items VALUES (?,?,?,?)", [
        ("NS-10001", "SKU-HDP200", 1, 129.99), ("NS-10002", "SKU-MUG4ST", 1, 24.00),
        ("NS-10003", "SKU-KTL01W", 1, 39.50),  ("NS-10004", "SKU-HDP200", 1, 129.99),
        ("NS-10005", "SKU-LMP300", 1, 45.50),  ("NS-10006", "SKU-JKT900", 1, 89.00),
    ])

    con.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?)", [
        ("NS-10001", "Royal Mail", "RM448812GB", "IN_TRANSIT", "Birmingham Mail Centre", _d(2)[:10], _d(-0.3)),
        ("NS-10002", "DPD",        "DPD7765102", "DELIVERED",  "Delivered - front door", _d(-3)[:10], _d(-3)),
        ("NS-10004", "DPD",        "DPD7765230", "DELIVERED",  "Delivered - signed by J WILSON", _d(-5)[:10], _d(-5)),
        ("NS-10006", "Royal Mail", "RM330017GB", "DELIVERED",  "Delivered - parcel locker", _d(-45)[:10], _d(-45)),
    ])
    con.commit()
    con.close()
    return path


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    if not os.path.exists(path):
        seed(path)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row      # rows behave like dictionaries
    return con


if __name__ == "__main__":
    print(f"Created fresh database at {seed()}")
