import os

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.utils import iface
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy

from carto.gui.extentselectionpanel import ExtentSelectionPanel
from carto.core.utils import MAX_ROWS


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "downloadfilteredlayerdialog.ui")
)


class DownloadFilteredLayerDialog(BASE, WIDGET):
    def __init__(self, table, connection, parent=None):
        parent = parent or iface.mainWindow()
        super(QDialog, self).__init__(parent)
        self.setupUi(self)
        self.table = table
        self.where = None
        self.limit = None
        self.connection = connection
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.extentPanel = ExtentSelectionPanel(self)
        self.grpSpatialFilter.layout().addWidget(self.extentPanel, 1, 0)

    def okClicked(self):
        statements = []
        if self.grpSpatialFilter.isChecked():
            extent = self.extentPanel.getExtent()
            if extent is None:
                self.bar.pushMessage("Invalid extent value", Qgis.Warning, duration=5)
                return
            destination_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            transform = QgsCoordinateTransform(
                extent.crs(), destination_crs, QgsProject.instance()
            )
            bottom_left = transform.transform(
                QgsPointXY(extent.xMinimum(), extent.yMinimum())
            )
            top_right = transform.transform(
                QgsPointXY(extent.xMaximum(), extent.yMaximum())
            )
            geom_column = self.table.geom_column()
            rectangle4326 = QgsRectangle(
                bottom_left.x(), bottom_left.y(), top_right.x(), top_right.y()
            )
            if self.connection.provider_type == "databricksRest":
                statements.append(
                    f"ST_INTERSECTS(ST_GEOMFROMWKB({geom_column}), ST_GEOMFROMTEXT('{rectangle4326.asWktPolygon()}'))"
                )
            elif self.connection.provider_type in ["postgres", "redshift"]:
                statements.append(
                    f"""ST_INTERSECTS(
                        ST_TRANSFORM({geom_column}, 4326),
                        ST_SET_SRID(ST_GEOMFROMTEXT('{rectangle4326.asWktPolygon()}'), 4326)
                    )"""
                )
            else:
                statements.append(
                    f"ST_INTERSECTS({geom_column}, ST_GEOGFROMTEXT('{rectangle4326.asWktPolygon()}'))"
                )
        elif self.grpWhereFilter.isChecked():
            statements.append(self.txtWhere.text())
        elif not self.grpLimit.isChecked():
            self.bar.pushMessage("Please select a filter", Qgis.Warning, duration=5)
            return
        else:
            statements.append("TRUE")
        self.where = " AND ".join(statements)
        if self.grpLimit.isChecked():
            limit = self.txtLimit.text()
            if not limit:
                self.bar.pushMessage(
                    "Maximum number of rows is required", Qgis.Warning, duration=5
                )
                return
            try:
                self.limit = int(limit)
            except ValueError:
                self.bar.pushMessage("Invalid number of rows", Qgis.Warning, duration=5)
                return
        else:
            self.limit = MAX_ROWS
        self.accept()
