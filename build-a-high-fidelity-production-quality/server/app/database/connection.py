from contextlib import contextmanager
import mysql.connector
from mysql.connector import pooling
from app.config.settings import settings

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="pharmsync_pool", pool_size=8,
            host=settings.db_host, user=settings.db_user, password=settings.db_password,
            database=settings.db_name, port=settings.db_port, autocommit=False,
        )
    return _pool

def get_connection():
    return get_pool().get_connection()

@contextmanager
def connection():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
