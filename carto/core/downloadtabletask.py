import traceback
import os
import base64

from qgis.core import (
    QgsTask,
    QgsGeometry,
)

from carto.core.layers import save_layer_metadata, filepath_for_table

from carto.core.logging import (
    error,
)

from carto.core.utils import (
    quote_for_provider,
    download_file,
)

from carto.core.api import (
    CARTO_API,
)

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsWkbTypes,
)


from qgis.PyQt.QtCore import QVariant


class DownloadTableTask(QgsTask):
    def __init__(self, table, where, limit):
        super().__init__(f"Download table {table.name}", QgsTask.CanCancel)
        self.exception = None
        self.table = table
        self.where = where
        self.limit = limit
        self.layer = None

    def run(self):
        if self.table.schema.database.connection.provider_type == "bigquery":
            return self._download_using_sql()
            # self._download_bigquery()
        else:
            return self._download_using_sql()

    def _download_bigquery(self):
        try:
            fqn = f"{self.table.schema.database.databaseid}.{self.table.schema.schemaid}.{self.table.tableid}"
            quoted_fqn = quote_for_provider(
                fqn, self.table.schema.database.connection.provider_type
            )
            query = f"(SELECT * FROM {quoted_fqn} WHERE {self.where}"
            ret = CARTO_API.execute_query(
                self.table.schema.database.connection.name,
                f"CALL cartobq.us.EXPORT_WITH_GDAL('''{query}''','GPKG',NULL,'{self.table.tableid}');",
            )
            url = ret["rows"][0]["result"]
            geopackage_file = self._filepath()
            os.makedirs(os.path.dirname(geopackage_file), exist_ok=True)
            download_file(url, geopackage_file)

            gpkglayer = QgsVectorLayer(geopackage_file, self.name, "ogr")
            gpkglayer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

            layer_metadata = {
                "pk": self.table.pk(),
                "columns": self.table.columns(),
                "geom_column": self.table.geom_column(),
                "can_write": self.table.schema.can_write(),
                "schema_changed": False,
                "provider_type": self.table.schema.database.connection.provider_type,
            }
            save_layer_metadata(gpkglayer, layer_metadata)
            self.layer = gpkglayer
            return True
        except Exception:
            self.exception = traceback.format_exc()
            error(self.exception)
            return False

    def _download_using_sql(self):
        try:
            self.setProgress(1)
            batch_size = min(100, self.limit or 100)
            offset = 0
            row_count = self.row_count()
            if row_count == 0:
                self.layer = None
                return True
            max_rows = min(self.limit or row_count, row_count)
            while True:
                where_with_offset = f"{self.where} LIMIT {batch_size} OFFSET {offset}"
                data = self.get_rows(where_with_offset)
                rows = data.get("rows", [])
                if offset == 0:
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
                    provider_type = self.table.schema.database.connection.provider_type
                    geom_type = None
                    if geom_field is not None:
                        for row in rows:
                            geom = row.get(geom_field)
                            if geom is not None:
                                if provider_type == "databricksRest":
                                    wkb_bytes = base64.b64decode(geom)
                                    geom = QgsGeometry()
                                    geom.fromWkb(wkb_bytes)
                                    if geom.isGeosValid():
                                        geom_type = QgsWkbTypes.displayString(
                                            geom.wkbType()
                                        )
                                else:
                                    geom_type = geom.get("type")
                                if geom_type is not None:
                                    break
                    layer = QgsVectorLayer(
                        f"{geom_type}?crs=EPSG:4326", self.table.name, "memory"
                    )
                    provider = layer.dataProvider()
                    provider.addAttributes(fields)
                    layer.updateFields()
                    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

                if len(rows) == 0:
                    break

                if self.isCanceled():
                    return False

                for item in rows:
                    feature = QgsFeature()
                    feature.setFields(fields)

                    for field in fields:
                        feature.setAttribute(field.name(), item.get(field.name()))

                    geom = item.get(geom_field)
                    if geom is not None:
                        if provider_type == "databricksRest":
                            wkb_bytes = base64.b64decode(geom)
                            geom = QgsGeometry()
                            geom.fromWkb(wkb_bytes)
                            feature.setGeometry(geom)
                        else:
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
                                    [QgsPointXY(x, y) for x, y in ring]
                                    for ring in coordinates
                                ]
                                feature.setGeometry(QgsGeometry.fromPolygonXY(polygon))
                            elif geom_type == "MultiPoint":
                                multipoint = [QgsPointXY(x, y) for x, y in coordinates]
                                feature.setGeometry(
                                    QgsGeometry.fromMultiPointXY(multipoint)
                                )
                            elif geom_type == "MultiLineString":
                                multiline = [
                                    [QgsPointXY(x, y) for x, y in line]
                                    for line in coordinates
                                ]
                                feature.setGeometry(
                                    QgsGeometry.fromMultiPolylineXY(multiline)
                                )
                            elif geom_type == "MultiPolygon":
                                multipolygon = [
                                    [
                                        [QgsPointXY(x, y) for x, y in ring]
                                        for ring in polygon
                                    ]
                                    for polygon in coordinates
                                ]
                                feature.setGeometry(
                                    QgsGeometry.fromMultiPolygonXY(multipolygon)
                                )
                    provider.addFeature(feature)

                if offset + batch_size >= max_rows:
                    break
                offset += batch_size
                self.setProgress(min((offset + batch_size) / row_count, 1) * 90)

            geopackage_file = filepath_for_table(
                self.table.schema.database.connection.name,
                self.table.schema.database.databaseid,
                self.table.schema.schemaid,
                self.table.tableid,
            )
            os.makedirs(os.path.dirname(geopackage_file), exist_ok=True)

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
            options.layerName = layer.name()
            _writer = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                geopackage_file,
                QgsProject.instance().transformContext(),
                options,
            )

            layer_metadata = {
                "pk": self.table.pk(),
                "columns": schema,
                "geom_column": geom_field,
                "can_write": self.table.schema.can_write(),
                "schema_changed": False,
                "provider_type": self.table.schema.database.connection.provider_type,
            }
            gpkglayer = QgsVectorLayer(
                f"{geopackage_file}|layername={self.table.name}", self.table.name, "ogr"
            )
            # gpkglayer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            save_layer_metadata(gpkglayer, layer_metadata)
            self.setProgress(100)
            self.layer = gpkglayer

            return True
        except Exception:
            self.exception = traceback.format_exc()
            error(self.exception)
            return False

    def get_rows(self, where=None):
        fqn = quote_for_provider(
            f"{self.table.schema.database.databaseid}.{self.table.schema.schemaid}.{self.table.tableid}",
            self.table.schema.database.connection.provider_type,
        )
        return CARTO_API.execute_query(
            self.table.schema.database.connection.name,
            f"""SELECT * FROM {fqn}
                WHERE {where} ;""",
        )

    def row_count(self):
        fqn = quote_for_provider(
            f"{self.table.schema.database.databaseid}.{self.table.schema.schemaid}.{self.table.tableid}",
            self.table.schema.database.connection.provider_type,
        )
        col_name = (
            "ROW_COUNT"
            if self.table.schema.database.connection.provider_type == "snowflake"
            else "row_count"
        )
        return CARTO_API.execute_query(
            self.table.schema.database.connection.name,
            f"""SELECT COUNT(*) AS row_count FROM {fqn}
                WHERE {self.where} ;""",
        )["rows"][0][col_name]
