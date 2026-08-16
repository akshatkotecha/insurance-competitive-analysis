import pyodbc
from config import SERVER, DATABASE, DRIVER

def get_connection():
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
    )
