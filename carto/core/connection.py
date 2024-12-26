from carto.core.api import CARTO_API
from carto.core.layers import filepath_for_table
from carto.core.utils import (
    quote_for_provider,
    prepare_multipart_sql,
)
from carto.gui.utils import waitcursor
from carto.core.importlayertask import ImportLayerTask
from carto.gui.authorization_manager import AUTHORIZATION_MANAGER
from carto.core.enums import AuthState

from qgis.core import (
    QgsVectorLayer,
    QgsMapLayer,
    Qgis,
    QgsApplication,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, QCoreApplication

from qgis.utils import iface


class CartoConnection(QObject):

    _connections = None

    connections_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        AUTHORIZATION_MANAGER.status_changed.connect(self._auth_status_changed)

    @waitcursor
    def provider_connections(self):
        if self._connections is None:
            try:
                connections = CARTO_API.connections()
                self._connections = [
                    ProviderConnection(
                        connection["id"],
                        connection["name"],
                        connection["provider_type"],
                    )
                    for connection in connections
                ]
            except Exception as e:
                self._connections = []
        return self._connections

    def clear_connections_cache(self):
        self._connections = None

    def _auth_status_changed(self, auth_status):
        try:
            self.clear_connections_cache()
            self.connections_changed.emit()
        except Exception as e:
            print(e)


CARTO_CONNECTION = CartoConnection()


class ProviderConnection:

    def __init__(self, connectionid, name, provider_type):
        self.provider_type = provider_type
        self.name = name
        self.connectionid = connectionid
        self._databases = None

    @waitcursor
    def databases(self):
        if self._databases is None:
            databases = CARTO_API.databases(self.connectionid)
            self._databases = [
                Database(database["id"], database["name"].replace("`", ""), self)
                for database in databases
            ]
        return self._databases


class Database:

    def __init__(self, databaseid, name, connection):
        self.databaseid = databaseid
        self.name = name
        self.connection = connection
        self._schemas = None

    @waitcursor
    def schemas(self):
        if self._schemas is None:
            schemas = CARTO_API.schemas(self.connection.connectionid, self.databaseid)
            self._schemas = [
                Schema(schema["id"], schema["name"], self) for schema in schemas
            ]
        return self._schemas


class Schema:

    def __init__(self, schemaid, name, database):
        self.schemaid = schemaid
        self.database = database
        self.name = name
        self._tables = None
        self._can_write = None
        self.tasks = []

    @waitcursor
    def tables(self):
        if self._tables is None:
            if self.database.connection.provider_type == "bigquery":
                MAXNROWS = 50000000
                MAXSIZEMB = 1000
                query = f"""
                    WITH geo_columns AS (
                        SELECT
                            table_catalog,
                            table_schema,
                            table_name,
                            -- Get only the first geography column
                            (ARRAY_AGG(column_name ORDER BY column_name LIMIT 1))[OFFSET(0)] as geo_column,
                            COUNT(*) as number_geography_columns
                        FROM
                            `{self.database.databaseid}.{self.schemaid}.INFORMATION_SCHEMA.COLUMNS`
                        WHERE
                            data_type = 'GEOGRAPHY'
                        GROUP BY 1, 2, 3
                        HAVING COUNT(*) > 0
                    ),
                    table_sizes AS (
                        SELECT
                            project_id as table_catalog,
                            dataset_id as table_schema,
                            table_id as table_name,
                            row_count,
                            ROUND(size_bytes / POW(1024, 2), 2) as table_size_mb
                        FROM `{self.database.databaseid}.{self.schemaid}.__TABLES__`
                        WHERE
                            size_bytes / POW(1024, 2) <= {MAXSIZEMB}
                            AND row_count <= {MAXNROWS}
                    )
                    SELECT
                        g.table_name,
                        s.row_count,
                        s.table_size_mb,
                        g.geo_column
                    FROM
                        geo_columns g
                    JOIN
                        table_sizes s
                    ON
                        g.table_catalog = s.table_catalog
                        AND g.table_schema = s.table_schema
                        AND g.table_name = s.table_name
                    ORDER BY g.table_name;
                """
                tables = CARTO_API.execute_query(self.database.connection.name, query)[
                    "rows"
                ]
                self._tables = [
                    Table(
                        table["table_name"],
                        table["table_name"],
                        table["table_size_mb"],
                        self,
                    )
                    for table in tables
                ]
            else:
                tables = CARTO_API.tables(
                    self.database.connection.connectionid,
                    self.database.databaseid,
                    self.schemaid,
                )
                self._tables = [
                    Table(table["id"], table["name"], table["size"], self)
                    for table in tables
                ]

        return self._tables

    def clear_tables_cache(self):
        self._tables = None

    @waitcursor
    def can_write(self):
        if self._can_write is None:
            fqn = quote_for_provider(
                f"{self.database.databaseid}.{self.schemaid}.__qgis_test_table",
                self.database.connection.provider_type,
            )
            sql = f"""
                DROP TABLE IF EXISTS {fqn};
                CREATE TABLE {fqn} AS (SELECT 1 AS id);
                DROP TABLE {fqn};
                """
            sql = prepare_multipart_sql(
                [sql], self.database.connection.provider_type, fqn
            )
            try:
                CARTO_API.execute_query(self.database.connection.name, sql)
                self._can_write = True
            except Exception as e:
                self._can_write = False
        return self._can_write

    @waitcursor
    def import_table(self, file_or_layer, tablename):
        if isinstance(file_or_layer, QgsMapLayer):
            layer = file_or_layer
        else:
            layer = QgsVectorLayer(file_or_layer, tablename, "ogr")
        fqn = f"{self.database.databaseid}.{self.schemaid}.{tablename}"

        task = ImportLayerTask(
            self.database.connection.name,
            self.database.connection.provider_type,
            fqn,
            layer,
        )

        def _show_terminated_message():
            iface.messageBar().pushMessage(
                f"Importing to {fqn} failed or was canceled",
                level=Qgis.Warning,
                duration=5,
            )

        def _show_completed_message():
            iface.messageBar().pushMessage(
                f"Layer correctly imported to {fqn}", level=Qgis.Success, duration=5
            )
            self.clear_tables_cache()

        task.taskTerminated.connect(_show_terminated_message)
        task.taskCompleted.connect(_show_completed_message)

        self.tasks.append(task)

        QgsApplication.taskManager().addTask(task)
        QCoreApplication.processEvents()
        iface.messageBar().pushMessage(
            "",
            "Import task added to QGIS task manager",
            level=Qgis.Info,
            duration=5,
        )


class Table:

    def __init__(self, tableid, name, size, schema):
        self.tableid = tableid
        self.name = name
        self.schema = schema
        self.size = size
        self._table_info = None

    @waitcursor
    def table_info(self):
        if self._table_info is None:
            self._table_info = CARTO_API.table_info(
                self.schema.database.connection.connectionid,
                self.schema.database.databaseid,
                self.schema.schemaid,
                self.tableid,
            )
        return self._table_info

    def columns(self):
        return self.table_info()["schema"]

    def geom_column(self):
        return self.table_info()["geomField"]

    @waitcursor
    def pk(self):
        if self.schema.database.connection.provider_type == "bigquery":
            sql = f"""
                    SELECT
                        column_name
                    FROM
                        `{self.schema.database.databaseid}.{self.schema.schemaid}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE`
                    WHERE
                        table_name = '{self.tableid}';
                    """
        elif self.schema.database.connection.provider_type == "postgres":
            sql = f"""
                    SELECT
                        a.attname as column_name
                    FROM
                        pg_index i
                    JOIN
                        pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE
                        i.indrelid = '{self.schema.database.databaseid}.{self.schema.schemaid}.{self.tableid}'::regclass
                    AND
                        i.indisprimary;
                    """
        elif self.schema.database.connection.provider_type == "redshift":
            sql = f"""
                    SELECT
                        column_name
                    FROM
                        information_schema.key_column_usage
                    WHERE
                        table_name = '{self.tableid}'
                    AND
                        constraint_name = 'PRIMARY';
                    """
        elif self.schema.database.connection.provider_type == "snowflake":
            sql = f"""
                    SELECT
                        constraint_name AS column_name
                    FROM
                        {self.schema.database.databaseid}.information_schema.table_constraints
                    WHERE
                        table_name = '{self.tableid}'
                    AND
                        constraint_type = 'PRIMARY KEY'
                    AND
                        table_schema = '{self.schema.schemaid}';
                    """
        else:
            return None
        ret = CARTO_API.execute_query(self.schema.database.connection.name, sql)
        if len(ret["rows"]) > 0:
            return ret["rows"][0]["column_name"]
        return None

    @waitcursor
    def get_rows(self, where=None):
        fqn = quote_for_provider(
            f"{self.schema.database.databaseid}.{self.schema.schemaid}.{self.tableid}",
            self.schema.database.connection.provider_type,
        )
        return CARTO_API.execute_query(
            self.schema.database.connection.name,
            f"""SELECT * FROM {fqn}
                WHERE {where} ;""",
        )

    def _filepath(self):
        return filepath_for_table(
            self.schema.database.connection.name,
            self.schema.database.databaseid,
            self.schema.schemaid,
            self.tableid,
        )
