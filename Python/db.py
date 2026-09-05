"""Single definition of how to reach SQL Server.

Every script and both chatbots build their connection from here, so moving the
project to another machine means setting environment variables rather than
editing nine files:

    set INSURANCE_DB_SERVER=YOURHOST\\SQLEXPRESS
    set INSURANCE_DB_NAME=INSURANCEDB

The defaults reproduce the original development machine, so the project still
runs with nothing set. Authentication is Windows/trusted by default; set
INSURANCE_DB_USER and INSURANCE_DB_PASSWORD to use a SQL login instead — those
are read from the environment and never written to disk.
"""

from __future__ import annotations

import os

import pyodbc

SERVER = os.environ.get("INSURANCE_DB_SERVER", r"AKSHAT\SQLEXPRESS")
DATABASE = os.environ.get("INSURANCE_DB_NAME", "INSURANCEDB")
DRIVER = os.environ.get("INSURANCE_DB_DRIVER", "ODBC Driver 17 for SQL Server")
USER = os.environ.get("INSURANCE_DB_USER")
PASSWORD = os.environ.get("INSURANCE_DB_PASSWORD")


def _build() -> str:
    parts = [f"DRIVER={{{DRIVER}}}", f"SERVER={SERVER}", f"DATABASE={DATABASE}"]
    if USER:
        parts += [f"UID={USER}", f"PWD={PASSWORD or ''}"]
    else:
        parts.append("Trusted_Connection=yes")
    return ";".join(parts) + ";"


CONN_STR = _build()


def connect(**kwargs) -> pyodbc.Connection:
    """A new connection. Callers that need one per thread (a threaded web
    server) should cache it themselves — see chatbot_core.get_conn()."""
    return pyodbc.connect(CONN_STR, **kwargs)


def describe() -> str:
    """Where we are pointed, without leaking a password into a log line."""
    auth = f"user {USER}" if USER else "trusted connection"
    return f"{SERVER}/{DATABASE} ({auth})"
