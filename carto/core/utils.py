import uuid
import requests
import shutil
from carto.gui.utils import waitcursor

from qgis.PyQt.QtCore import QSettings

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
    elif provider_type == "postgres":
        return f'"{value}"'
    elif provider_type == "redshift":
        return f'"{value}"'
    elif provider_type == "snowflake":
        return f'"{value}"'
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
            BEGIN;
                {joined}
            END;
            """
