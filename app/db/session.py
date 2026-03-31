from collections.abc import Generator

import psycopg
from fastapi import Request
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base


def create_session_factory(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
        return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    engine_kwargs: dict = {
        "future": True,
        "pool_pre_ping": True,
    }
    connect_args: dict = {}

    # Managed Postgres poolers (Supabase/Neon) behave best when SQLAlchemy avoids
    # reset/rollback cycles and native hstore introspection on connect.
    if "pooler.supabase.com" in database_url:
        engine_kwargs["isolation_level"] = "AUTOCOMMIT"
        engine_kwargs["pool_reset_on_return"] = None
        engine_kwargs["skip_autocommit_rollback"] = True
        engine_kwargs["use_native_hstore"] = False
        engine_kwargs["client_encoding"] = "utf8"
        if ":6543/" in database_url:
            engine_kwargs["poolclass"] = NullPool
            connect_args["prepare_threshold"] = None

    # Neon pooled/direct connections behind PgBouncer are most stable for our
    # startup path when SQLAlchemy avoids reset/rollback cycles on connect.
    if "neon.tech" in database_url:
        engine_kwargs["isolation_level"] = "AUTOCOMMIT"
        engine_kwargs["pool_reset_on_return"] = None
        engine_kwargs["skip_autocommit_rollback"] = True
        engine_kwargs["use_native_hstore"] = False

    engine = create_engine(
        database_url,
        connect_args=connect_args,
        **engine_kwargs,
    )
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(engine: Engine, database_url: str | None = None) -> None:
    if database_url and ("neon.tech" in database_url or "pooler.supabase.com" in database_url):
        _bootstrap_neon_schema(database_url)
        return

    Base.metadata.create_all(bind=engine)
    _apply_compat_migrations(engine)


def _bootstrap_neon_schema(database_url: str) -> None:
    raw_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    dialect = postgresql.dialect()

    with psycopg.connect(raw_url) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            for table in Base.metadata.sorted_tables:
                create_table_sql = str(CreateTable(table).compile(dialect=dialect))
                try:
                    cursor.execute(create_table_sql)
                except psycopg.errors.DuplicateTable:
                    pass

                for index in table.indexes:
                    create_index_sql = str(CreateIndex(index).compile(dialect=dialect))
                    try:
                        cursor.execute(create_index_sql)
                    except (psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
                        pass


def _apply_compat_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "doors" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("doors")}
    with engine.begin() as connection:
        if "door_uid" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN door_uid VARCHAR(32)"))
            rows = connection.execute(text("SELECT id FROM doors")).fetchall()
            for row in rows:
                base = str(row[0]).replace("-", "").upper()[:10]
                connection.execute(
                    text("UPDATE doors SET door_uid = :door_uid WHERE id = :id"),
                    {"door_uid": base, "id": row[0]},
                )
        else:
            rows = connection.execute(text("SELECT id, door_uid FROM doors")).fetchall()
            for row in rows:
                current_uid = str(row[1] or "").strip().upper()
                if not current_uid:
                    normalized_uid = str(row[0]).replace("-", "").upper()[:10]
                elif current_uid.startswith("DOOR-"):
                    normalized_uid = current_uid.removeprefix("DOOR-")
                else:
                    normalized_uid = current_uid
                connection.execute(
                    text("UPDATE doors SET door_uid = :door_uid WHERE id = :id"),
                    {"door_uid": normalized_uid, "id": row[0]},
                )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_doors_door_uid ON doors (door_uid)")
        )
        if "lock_uid_hash" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN lock_uid_hash VARCHAR(128)"))
        if "lock_uid_encrypted" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN lock_uid_encrypted VARCHAR(4096)"))
        if "qr_secret_encrypted" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN qr_secret_encrypted VARCHAR(4096)"))
        if "qr_secret_rotated_at" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN qr_secret_rotated_at TIMESTAMP"))
        if "current_qr_code_encrypted" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN current_qr_code_encrypted VARCHAR(4096)"))
        if "current_qr_issued_at" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN current_qr_issued_at TIMESTAMP"))
        if "current_qr_expires_at" not in columns:
            connection.execute(text("ALTER TABLE doors ADD COLUMN current_qr_expires_at TIMESTAMP"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_doors_lock_uid_hash "
                "ON doors (lock_uid_hash) WHERE lock_uid_hash IS NOT NULL"
            )
        )

    if "lock_devices" not in table_names:
        return

    lock_columns = {column["name"] for column in inspector.get_columns("lock_devices")}
    with engine.begin() as connection:
        if "lock_id_hash" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN lock_id_hash VARCHAR(128)"))
            connection.execute(text("UPDATE lock_devices SET lock_id_hash = device_uid_hash WHERE lock_id_hash IS NULL"))
        if "lock_id_encrypted" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN lock_id_encrypted VARCHAR(4096)"))
            connection.execute(
                text(
                    "UPDATE lock_devices SET lock_id_encrypted = device_uid_encrypted "
                    "WHERE lock_id_encrypted IS NULL"
                )
            )
        if "api_key_hash" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN api_key_hash VARCHAR(128)"))
        if "api_key_encrypted" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN api_key_encrypted VARCHAR(4096)"))
        if "port_name" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN port_name VARCHAR(128)"))
        if "status" not in lock_columns:
            connection.execute(
                text("ALTER TABLE lock_devices ADD COLUMN status VARCHAR(32) DEFAULT 'configured'")
            )
        if "esp8266_uid_encrypted" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN esp8266_uid_encrypted VARCHAR(4096)"))
        if "esp32_uid_encrypted" not in lock_columns:
            connection.execute(text("ALTER TABLE lock_devices ADD COLUMN esp32_uid_encrypted VARCHAR(4096)"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_lock_devices_lock_id_hash "
                "ON lock_devices (lock_id_hash)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_lock_devices_device_uid_hash "
                "ON lock_devices (device_uid_hash)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_lock_devices_api_key_hash "
                "ON lock_devices (api_key_hash)"
            )
        )

    if "face_photo_submissions" not in table_names:
        return

    face_columns = {column["name"] for column in inspector.get_columns("face_photo_submissions")}
    with engine.begin() as connection:
        if "face_map_encrypted" not in face_columns:
            connection.execute(text("ALTER TABLE face_photo_submissions ADD COLUMN face_map_encrypted TEXT"))
        if "face_quality_score" not in face_columns:
            connection.execute(text("ALTER TABLE face_photo_submissions ADD COLUMN face_quality_score DOUBLE PRECISION"))
        if "face_model_version" not in face_columns:
            connection.execute(text("ALTER TABLE face_photo_submissions ADD COLUMN face_model_version VARCHAR(128)"))
        if "processing_error" not in face_columns:
            connection.execute(text("ALTER TABLE face_photo_submissions ADD COLUMN processing_error TEXT"))
        if "processed_at" not in face_columns:
            connection.execute(text("ALTER TABLE face_photo_submissions ADD COLUMN processed_at TIMESTAMP"))

    if "telegram_guest_bindings" not in table_names:
        return


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
