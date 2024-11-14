import os

from qgis.core import Qgis
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog

from carto.core.connection import CartoConnection

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "selectprimarykeydialog.ui")
)


class SelectPrimaryKeyDialog(BASE, WIDGET):
    def __init__(self, table, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)
        self.table = table

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.initGui(table)

        self.pk = None

    def initGui(self, table):
        columns = [field.name() for field in table.fields()]
        self.comboPK.addItems(columns)

    def okClicked(self):
        self.pk = self.comboPK.currentText()
        self.accept()
