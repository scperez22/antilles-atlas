from logging.config import fileConfig

from alembic import context
from geoalchemy2.alembic_helpers import include_object as geo_include_object
from geoalchemy2.alembic_helpers import render_item as geo_render_item
from geoalchemy2.alembic_helpers import writer as geo_writer
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (ensures models are registered on Base.metadata)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# PostGIS creates its own system tables/views for spatial reference and
# raster catalogs. Autogenerate must never try to manage these, or it
# will emit spurious drop/create operations against tables Postgres owns.
POSTGIS_SYSTEM_TABLES = {
    "spatial_ref_sys",
    "geography_columns",
    "geometry_columns",
    "raster_columns",
    "raster_overviews",
}


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and name in POSTGIS_SYSTEM_TABLES:
        return False
    # Defer to GeoAlchemy2's own filter for spatial-index-related objects,
    # which is what prevents autogenerate from emitting a duplicate
    # create_index for the GiST index GeoAlchemy2 already creates as a
    # side effect of table creation.
    return geo_include_object(object_, name, type_, reflected, compare_to)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_item=geo_render_item,
        process_revision_directives=geo_writer,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql("SET search_path TO public ")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_item=geo_render_item,
            process_revision_directives=geo_writer,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
