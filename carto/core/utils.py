import uuid
import requests
import shutil
from carto.gui.utils import waitcursor

from qgis.PyQt.QtCore import QSettings, QVariant

NAMESPACE = "carto"
MAXROWS = "maxrows"
TOKEN = "token"

setting_types = {}


def setSetting(name, value):
    QSettings().setValue(f"{NAMESPACE}/{name}", value)


def setting(name):
    v = QSettings().value(f"{NAMESPACE}/{name}", None)
    if setting_types.get(name, str) == bool:
        return str(v).lower() == str(True).lower()
    else:
        return v


@waitcursor
def download_file(url, filename):
    with requests.get(url, stream=True) as r:
        with open(filename, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def quote_for_provider(value, provider_type):
    if provider_type == "bigquery":
        return f"`{value}`"
    elif provider_type in ["postgres", "redshift"]:
        parts = value.split(".")
        if len(parts) == 3:
            return f""""{parts[0].replace('"', '')}".{parts[1]}.{parts[2]}"""
        else:
            return value
    elif provider_type == "databricks":
        return ".".join([f"`{v}`" for v in value.split(".")])
    return value


def prepare_multipart_sql(statements, provider, fqn):
    joined = "\n".join(statements)
    if provider == "redshift":
        schema_path = ".".join(fqn.split(".")[:2])
        proc_name = f"{schema_path}.carto_{uuid.uuid4().hex}"
        return f"""
            CREATE OR REPLACE PROCEDURE ${proc_name}()
                AS $$
                BEGIN
                  {query}
                END;
                $$ LANGUAGE plpgsql;

            CALL {proc_name}();
            DROP PROCEDURE {proc_name}();`
            """
    elif provider == "postgres":
        return f"""
                DO $$
                BEGIN
                    {joined}
                END;
                $$;
                """
    else:
        return f"""
            BEGIN
                {joined}
            END;
            """


def provider_data_type_from_qgis_type(qgis_type, provider):
    provider = provider.lower()

    type_mapping = {
        "bigquery": {
            QVariant.String: "STRING",
            "text": "STRING",
            QVariant.Int: "INT64",
            QVariant.LongLong: "INT64",
            QVariant.Double: "FLOAT64",
            QVariant.Bool: "BOOL",
            "geometry": "GEOGRAPHY",
        },
        "snowflake": {
            QVariant.String: "VARCHAR",
            QVariant.Int: "NUMBER(38,0)",
            QVariant.LongLong: "NUMBER(38,0)",
            QVariant.Double: "FLOAT",
            QVariant.Bool: "BOOL",
            "geometry": "GEOGRAPHY",
        },
        "redshift": {
            QVariant.String: "VARCHAR(MAX)",
            QVariant.Int: "BIGINT",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE PRECISION",
            QVariant.Bool: "BOOLEAN",
            "geometry": "GEOMETRY",
        },
        "postgres": {
            QVariant.String: "TEXT",
            QVariant.Int: "INTEGER",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE PRECISION",
            QVariant.Bool: "BOOLEAN",
            "geometry": "GEOMETRY",
        },
        "databricks": {
            QVariant.String: "VARCHAR",
            QVariant.Int: "BIGINT",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE",
            QVariant.Bool: "BOOLEAN",
            "geometry": "STRING",
        },
    }

    mapping = type_mapping.get(provider)

    if not mapping:
        raise ValueError(f"Unsupported provider: {provider}")

    db_type = mapping.get(qgis_type, "STRING")
    return db_type


def prepare_geo_value_for_provider(provider_type, geom):
    if provider_type == "databricks":
        return f"'{geom.asWkt()}'"
    else:
        wkb = geom.asWkb().toHex().data().decode()
        if provider_type in ["bigquery", "snowflake"]:
            return f"ST_GEOGFROMWKB('{wkb}')"
        else:
            return f"ST_GEOMFROMWKB(DECODE('{wkb}', 'hex'))"
