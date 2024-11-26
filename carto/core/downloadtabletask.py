import traceback
import os

from qgis.core import (
    QgsTask,
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
    CartoApi,
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
)


from qgis.PyQt.QtCore import QVariant


class DownloadTableTask(QgsTask):
    def __init__(
        self,
        table,
        where,
    ):
        super().__init__(f"Download table {table.name}", QgsTask.CanCancel)
        self.exception = None
        self.table = table
        self.where = where
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
            ret = CartoApi.instance().execute_query(
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
            batch_size = 100
            offset = 0
            row_count = self.row_count()
            if row_count == 0:
                self.layer = None
                return True
            while True:
                where_with_offset = f"{self.where} OFFSET {offset}"
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

                    if geom_field is not None:
                        geom_type = rows[0][geom_field]["type"]
                    else:
                        geom_type = None
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

            """
            QgsVectorFileWriter.writeAsVectorFormat(
                layer,
                geopackage_file,
                "UTF-8",
                layer.crs(),
                "GPKG",
                layerOptions=["OVERWRITE=YES"],
            )
            gpkglayer = QgsVectorLayer(geopackage_file, self.table.name, "ogr")
            """

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
            print(layer.crs())
            print(gpkglayer.crs())
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
        return CartoApi.instance().execute_query(
            self.table.schema.database.connection.name,
            f"""SELECT * FROM {fqn}
                WHERE {where} ;""",
        )

    def row_count(self):
        fqn = quote_for_provider(
            f"{self.table.schema.database.databaseid}.{self.table.schema.schemaid}.{self.table.tableid}",
            self.table.schema.database.connection.provider_type,
        )
        return CartoApi.instance().execute_query(
            self.table.schema.database.connection.name,
            f"""SELECT COUNT(*) AS row_count FROM {fqn}
                WHERE {self.where} ;""",
        )["rows"][0]["row_count"]
