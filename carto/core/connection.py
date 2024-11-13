import os
from carto.core.api import CartoApi
from carto.core.layers import filepath_for_table, save_layer_metadata
from carto.core.utils import setting, MAXROWS

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsApplication,
    QgsSettings,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsCoordinateTransform,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant

from qgis.utils import iface


class CartoConnection(object):

    __instance = None
    _connections = None

    @staticmethod
    def instance():
        if CartoConnection.__instance is None:
            CartoConnection()
        return CartoConnection.__instance

    def __init__(self):
        if CartoConnection.__instance is not None:
            raise Exception("Singleton class")

        CartoConnection.__instance = self

    def provider_connections(self):
        if self._connections is None:
            connections = CartoApi.instance().connections()
            self._connections = [
                ProviderConnection(
                    connection["id"], connection["name"], connection["provider_type"]
                )
                for connection in connections
            ]
        return self._connections

    def clear(self):  # TODO link this to API logout signal
        self._connections = None


class ProviderConnection:

    def __init__(self, connectionid, name, provider_type):
        self.provider_type = provider_type
        self.name = name
        self.connectionid = connectionid
        self._databases = None

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

    def tables(self):
        if self._tables is None:
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

    def can_write(self):
        path = f"{self.database.databaseid}.{self.schemaid}"
        sql = f"""BEGIN
                    CREATE OR REPLACE TABLE `{path}.__qgis_test_table` AS (SELECT 1 as id);
                    DROP TABLE `{path}.__qgis_test_table`;
                END;
            """
        try:
            CartoApi.instance().execute_query(self.database.connection.name, sql)
            return True
        except Exception as e:
            return False

    def import_table(self, file_or_layer, tablename):
        if isinstance(file_or_layer, QgsMapLayer):
            isSupported = True  # TODO
            if isSupported:
                filepath = file_or_layer.source()
            else:
                # TODO
                filepath = file_or_layer.source()
        else:
            filepath = file_or_layer
        fqn = f"{self.database.databaseid}.{self.schemaid}.{tablename}"
        try:
            CartoApi.instance().import_table_from_file(
                self.database.connection.name, fqn, filepath
            )
            iface.messageBar().pushMessage(
                "Imported",
                "The layer has been imported",
                level=Qgis.Success,
                duration=10,
            )
        except Exception as e:
            iface.messageBar().pushMessage(
                "Import failed",
                "Please check your layer and try again",
                level=Qgis.Warning,
                duration=10,
            )


class Table:

    def __init__(self, tableid, name, size, schema):
        self.tableid = tableid
        self.name = name
        self.schema = schema
        self.size = size
        self._table_info = None

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

    def pk(self):
        sql = f"""
                SELECT
                    column_name
                FROM
                    `{self.schema.database.databaseid}.{self.schema.schemaid}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE`
                WHERE
                    table_name = '{self.tableid}';
                """
        ret = CartoApi.instance().execute_query(
            self.schema.database.connection.name, sql
        )
        if len(ret["rows"]) > 0:
            return ret["rows"][0]["column_name"]
        return None

    def get_rows(self, where=None):
        return CartoApi.instance().execute_query(
            self.schema.database.connection.name,
            f"""SELECT * FROM `{self.schema.database.databaseid}.{self.schema.schemaid}.{self.tableid}`
                {f"WHERE {where}" if where else ""}
                LIMIT {setting(MAXROWS) or 1000};""",
        )

    def _filepath(self):
        return filepath_for_table(
            self.schema.database.connection.name,
            self.schema.database.databaseid,
            self.schema.schemaid,
            self.tableid,
        )

    def download(self, where=None):
        data = self.get_rows(where)

        print(data)
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

        layer_metadata = {"pk": self.pk(), "columns": schema, "geom_column": geom_field}
        save_layer_metadata(gpkglayer, layer_metadata)
        return gpkglayer
