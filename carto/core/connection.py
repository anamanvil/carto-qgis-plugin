import os
from carto.core.api import CartoApi
from carto.core.layers import filepath_for_table, save_layer_metadata
from carto.core.utils import (
    download_file,
    quote_for_provider,
    prepare_multipart_sql,
)
from carto.gui.utils import waitcursor
from carto.core.importlayertask import ImportLayerTask
from carto.gui.authorization_manager import AUTHORIZATION_MANAGER
from carto.core.enums import AuthState

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    Qgis,
    QgsApplication,
)
from qgis.PyQt.QtCore import QVariant, QObject, pyqtSignal, QCoreApplication

from qgis.utils import iface


class CartoConnection(QObject):

    __instance = None
    _connections = None

    connections_changed = pyqtSignal()

    @staticmethod
    def instance():
        if CartoConnection.__instance is None:
            CartoConnection.__instance = CartoConnection()
        return CartoConnection.__instance

    def __init__(self):
        super().__init__()
        if CartoConnection.__instance is not None:
            raise Exception("Singleton class")
        AUTHORIZATION_MANAGER.status_changed.connect(self._auth_status_changed)

    @waitcursor
    def provider_connections(self):
        if self._connections is None:
            connections = CartoApi.instance().connections()
            self._connections = [
                ProviderConnection(
                    connection["id"], connection["name"], connection["provider_type"]
                )
                for connection in connections
            ]
        self.connections_changed.emit()
        return self._connections

    def _auth_status_changed(self, auth_status):
        if auth_status == AuthState.NotAuthorized:
            self._connections = None
        self.connections_changed.emit()


class ProviderConnection:

    def __init__(self, connectionid, name, provider_type):
        self.provider_type = provider_type
        self.name = name
        self.connectionid = connectionid
        self._databases = None

    @waitcursor
    def databases(self):
        if self._databases is None:
            databases = CartoApi.instance().databases(self.connectionid)
            self._databases = [
                Database(database["id"], database["name"], self)
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
            schemas = CartoApi.instance().schemas(
                self.connection.connectionid, self.databaseid
            )
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
        print("tables")
        print(self._tables)
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
                tables = CartoApi.instance().execute_query(
                    self.database.connection.name, query
                )["rows"]
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
                tables = CartoApi.instance().tables(
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
                CartoApi.instance().execute_query(self.database.connection.name, sql)
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
            "Order download task added to QGIS task manager",
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
            self._table_info = CartoApi.instance().table_info(
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
        ret = CartoApi.instance().execute_query(
            self.schema.database.connection.name, sql
        )
        if len(ret["rows"]) > 0:
            return ret["rows"][0]["column_name"]
        return None

    @waitcursor
    def get_rows(self, where=None):
        fqn = quote_for_provider(
            f"{self.schema.database.databaseid}.{self.schema.schemaid}.{self.tableid}",
            self.schema.database.connection.provider_type,
        )
        return CartoApi.instance().execute_query(
            self.schema.database.connection.name,
            f"""SELECT * FROM {fqn}
                {f"WHERE {where}" if where else ""};""",
        )

    def _filepath(self):
        return filepath_for_table(
            self.schema.database.connection.name,
            self.schema.database.databaseid,
            self.schema.schemaid,
            self.tableid,
        )

    def download(self, where=None):
        if self.schema.database.connection.provider_type == "bigquery":
            return self._download_bigquery(where)
        else:
            return self._download_using_sql(where)

    @waitcursor
    def _download_bigquery(self, where=None):
        fqn = f"{self.schema.database.databaseid}.{self.schema.schemaid}.{self.tableid}"
        if where is None:
            query = fqn
        else:
            quoted_fqn = quote_for_provider(
                fqn, self.schema.database.connection.provider_type
            )
            query = f"{quoted_fqn} WHERE {where}"
        ret = CartoApi.instance().execute_query(
            self.schema.database.connection.name,
            f"CALL cartobq.us.EXPORT_WITH_GDAL('''{query}''','GPKG',NULL,'{self.tableid}');",
        )
        url = ret["rows"][0]["result"]
        geopackage_file = self._filepath()
        os.makedirs(os.path.dirname(geopackage_file), exist_ok=True)
        download_file(url, geopackage_file)

        gpkglayer = QgsVectorLayer(geopackage_file, self.name, "ogr")
        gpkglayer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        layer_metadata = {
            "pk": self.pk(),
            "columns": self.columns(),
            "geom_column": self.geom_column(),
            "can_write": self.schema.can_write(),
            "schema_changed": False,
            "provider_type": self.schema.database.connection.provider_type,
        }
        save_layer_metadata(gpkglayer, layer_metadata)
        return gpkglayer

    @waitcursor
    def _download_using_sql(self, where=None):
        data = self.get_rows(where)

        geopackage_file = self._filepath()

        rows = data.get("rows", [])
        schema = data.get("schema", [])

        fields = QgsFields()
        geom_field = None
        for field in schema:
            field_name = field["name"]
            field_type = field["type"]
            if field_type == "string":
                fields.append(QgsField(field_name, QVariant.String))
            elif field_type == "integer":
                fields.append(QgsField(field_name, QVariant.Int))
            elif field_type in ["double", "number"]:
                fields.append(QgsField(field_name, QVariant.Double))
            elif field_type == "geometry":
                geom_field = field_name

        if geom_field is not None:
            geom_type = rows[0][geom_field]["type"]
        else:
            geom_type = None
        layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:4326", self.name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(fields)
        layer.updateFields()

        for item in rows:
            feature = QgsFeature()
            feature.setFields(fields)

            for field in fields:
                feature.setAttribute(field.name(), item.get(field.name()))

            geom = item.get(geom_field, {})
            if geom:
                geom_type = geom.get("type")
                coordinates = geom.get("coordinates", [])

                if geom_type == "Point" and len(coordinates) == 2:
                    point = QgsPointXY(coordinates[0], coordinates[1])
                    feature.setGeometry(QgsGeometry.fromPointXY(point))
                elif geom_type == "LineString":
                    line = [QgsPointXY(x, y) for x, y in coordinates]
                    feature.setGeometry(QgsGeometry.fromPolylineXY(line))
                elif geom_type == "Polygon":
                    polygon = [
                        [QgsPointXY(x, y) for x, y in ring] for ring in coordinates
                    ]
                    feature.setGeometry(QgsGeometry.fromPolygonXY(polygon))
                elif geom_type == "MultiPoint":
                    multipoint = [QgsPointXY(x, y) for x, y in coordinates]
                    feature.setGeometry(QgsGeometry.fromMultiPointXY(multipoint))
                elif geom_type == "MultiLineString":
                    multiline = [
                        [QgsPointXY(x, y) for x, y in line] for line in coordinates
                    ]
                    feature.setGeometry(QgsGeometry.fromMultiPolylineXY(multiline))
                elif geom_type == "MultiPolygon":
                    multipolygon = [
                        [[QgsPointXY(x, y) for x, y in ring] for ring in polygon]
                        for polygon in coordinates
                    ]
                    feature.setGeometry(QgsGeometry.fromMultiPolygonXY(multipolygon))
            provider.addFeature(feature)

        os.makedirs(os.path.dirname(geopackage_file), exist_ok=True)

        QgsVectorFileWriter.writeAsVectorFormat(
            layer,
            geopackage_file,
            "UTF-8",
            layer.crs(),
            "GPKG",
            layerOptions=["OVERWRITE=YES"],
        )
        gpkglayer = QgsVectorLayer(geopackage_file, self.name, "ogr")
        gpkglayer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        layer_metadata = {
            "pk": self.pk(),
            "columns": schema,
            "geom_column": geom_field,
            "can_write": self.schema.can_write(),
            "schema_changed": False,
            "provider_type": self.schema.database.connection.provider_type,
        }
        save_layer_metadata(gpkglayer, layer_metadata)
        return gpkglayer
