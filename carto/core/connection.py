import os
from carto.core.api import CartoApi
from carto.layers import filepath_for_table, save_layer_metadata

import json
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
)
from qgis.PyQt.QtCore import QVariant


class CartoConnection(object):

    def __init__(self):
        pass

    def provider_connections(self):
        connections = CartoApi.instance().connections()
        return [
            ProviderConnection(
                connection["id"], connection["name"], connection["provider_type"]
            )
            for connection in connections
        ]


class ProviderConnection:

    def __init__(self, connectionid, name, provider_type):
        self.provider_type = provider_type
        self.name = name
        self.connectionid = connectionid

    def databases(self):
        databases = CartoApi.instance().databases(self.connectionid)
        return [
            Database(database["id"], database["name"], self) for database in databases
        ]


class Database:

    def __init__(self, databaseid, name, connection):
        self.databaseid = databaseid
        self.name = name
        self.connection = connection

    def schemas(self):
        schemas = CartoApi.instance().schemas(
            self.connection.connectionid, self.databaseid
        )
        return [Schema(schema["id"], schema["name"], self) for schema in schemas]


class Schema:

    def __init__(self, schemaid, name, database):
        self.schemaid = schemaid
        self.database = database
        self.name = name

    def tables(self):
        tables = CartoApi.instance().tables(
            self.database.connection.connectionid,
            self.database.databaseid,
            self.schemaid,
        )
        return [Table(table["id"], table["name"], self) for table in tables]

    def can_write(self):
        sql = f"""
                CREATE TEMPORARY TABLE __qgis_test_table (id INT64);
            """
        try:
            CartoApi.instance().execute_query(self.database.connection.name, sql)
            return True
        except Exception as e:
            return False


class Table:

    def __init__(self, tableid, name, schema):
        self.tableid = tableid
        self.name = name
        self.schema = schema

    def columns(self):
        return CartoApi.instance().columns(
            self.schema.database.connection.connectionid,
            self.schema.database.databaseid,
            self.schema.schemaid,
            self.tableid,
        )

    def pk(self):
        sql = f"""
                SELECT
                    column_name
                FROM
                    `{self.schema.database.databaseid}.{self.schema.schemaid}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE`
                WHERE
                    table_name = '{self.tableid}'
                AND constraint_name LIKE '%PRIMARY%';
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
                LIMIT {QgsSettings().value("carto/rowlimit", 1000)};""",
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
            elif field_type == "double":
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

        layer_metadata = {"pk": self.pk(), "columns": schema, "geom_column": geom_field}
        save_layer_metadata(gpkglayer, layer_metadata)
        return gpkglayer
