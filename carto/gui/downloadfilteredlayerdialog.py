import os

from qgis.core import Qgis
from qgis.utils import iface
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog

from carto.gui.extentselectionpanel import ExtentSelectionPanel


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "downloadfilteredlayerdialog.ui")
)


class DownloadFilteredLayerDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        parent = parent or iface.mainWindow()
        super(QDialog, self).__init__(parent)
        self.setupUi(self)
        self.where = None

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.extentPanel = ExtentSelectionPanel(self)
        self.grpSpatialFilter.layout().addWidget(self.extentPanel, 1, 0)
        self.grpSpatialFilter.toggled.connect(self.onSpatialFilterToggled)

    def okClicked(self):
        if self.grpSpatialFilter.isChecked():
            extent = self.extentPanel.getExtent()
            if extent is None:
                self.bar.pushMessage("Invalid extent value", Qgis.Warning, duration=5)
                return
            self.where = "#todo"
        elif self.grpWhereFilter.isChecked():
            self.where = self.txtWhere.currentText()
        else:
            self.bar.pushMessage("Please select a filter", Qgis.Warning, duration=5)
            return
        self.accept()
