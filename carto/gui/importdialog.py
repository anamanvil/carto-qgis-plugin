import os

from qgis.core import Qgis
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog

from carto.core.connection import CartoConnection

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "importdialog.ui")
)


class ImportDialog(BASE, WIDGET):
    def __init__(self, connection, database, schema, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.initGui(connection, database, schema)

        self.comboConnection.currentIndexChanged.connect(self.connectionChanged)
        self.comboDatabase.currentIndexChanged.connect(self.databaseChanged)

        self.file_or_layer = None
        self.tablename = None
        self.schema = None

    def initGui(self, connection, database, schema):
        connections = CartoConnection.instance().provider_connections()
        self.comboConnection.addItems([connection.name for connection in connections])
        idx = self.comboConnection.findText(connection.name)
        self.comboConnection.setCurrentIndex(idx if idx != -1 else 0)
        self.connectionChanged(self.comboConnection.currentIndex())
        if database is not None:
            idx = self.comboDatabase.findText(database.name)
            self.comboDatabase.setCurrentIndex(idx if idx != -1 else 0)
            self.databaseChanged(self.comboDatabase.currentIndex())
        if schema is not None:
            idx = self.comboSchema.findText(schema.name)
            self.comboSchema.setCurrentIndex(idx if idx != -1 else 0)

    def connectionChanged(self, index):
        connection = CartoConnection.instance().provider_connections()[index]
        self.comboDatabase.clear()
        self.comboSchema.clear()
        self.comboDatabase.addItems(
            [database.name for database in connection.databases()]
        )

    def databaseChanged(self, index):
        database = (
            CartoConnection.instance()
            .provider_connections()[self.comboConnection.currentIndex()]
            .databases()[index]
        )
        self.comboSchema.clear()
        self.comboSchema.addItems([schema.name for schema in database.schemas()])

    def okClicked(self):
        if self.tabWidget.currentIndex() == 0:
            self.file_or_layer = self.comboLayer.currentLayer()
        else:
            self.file_or_layer = self.txtFile.filePath()
        if not self.file_or_layer:
            self.bar.pushMessage("File or layer is required", Qgis.Warning, duration=5)
            return
        self.tablename = self.txtTablename.text()
        if not self.tablename:
            if self.tabWidget.currentIndex() == 0:
                self.tablename = self.comboLayer.currentLayer().name()
            else:
                self.tablename = os.path.basename(self.txtFile.filePath()).split(".")[0]
            self.tablename = "".join([c for c in self.tablename if c.isalnum()])
        self.schema = (
            CartoConnection.instance()
            .provider_connections()[self.comboConnection.currentIndex()]
            .databases()[self.comboDatabase.currentIndex()]
            .schemas()[self.comboSchema.currentIndex()]
        )
        self.accept()
