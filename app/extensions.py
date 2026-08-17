"""Flask extensions, created once and bound to the app in the factory.

Keeping extension objects in a dedicated module avoids circular imports:
models, services and blueprints all import from here rather than from the
application package.
"""

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event

#: SQLAlchemy ORM - database models bind to this instance.
db = SQLAlchemy()

#: Flask-Migrate (Alembic) - schema migrations.
migrate = Migrate()

#: CSRF protection for all state-changing web forms.
csrf = CSRFProtect()


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Turn on SQLite foreign-key enforcement for a connection.

    SQLite ignores ``FOREIGN KEY`` clauses unless the ``foreign_keys`` pragma
    is set per connection.  This listener is attached only to SQLite engines
    (see ``create_app``) so other backends such as PostgreSQL are unaffected.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def register_sqlite_pragmas(app: Flask) -> None:
    """Attach the FK pragma listener to every SQLite engine of the app."""
    with app.app_context():
        for engine in db.engines.values():
            if engine.dialect.name == "sqlite":
                event.listen(engine, "connect", _enable_sqlite_foreign_keys)
