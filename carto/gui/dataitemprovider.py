import os
import sip
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsDataItemProvider,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataProvider,
    QgsProject,
    QgsSettings,
)
from qgis.core import Qgis, QgsMapLayer
from qgis.utils import iface

from carto.core.connection import CartoConnection
from carto.core.api import CartoApi
from carto.layers import layer_metadata
from carto.gui.settingsdialog import SettingsDialog
from carto.gui.importdialog import ImportDialog
from carto.gui.downloadfilteredlayerdialog import DownloadFilteredLayerDialog

IMGS_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "imgs")

carto_connection = CartoConnection()


pluginPath = os.path.dirname(__file__)


def icon(f):
    return QIcon(os.path.join(pluginPath, "img", f))


cartoIcon = icon("carto.png")
databaseIcon = icon("database.png")
schemaIcon = icon("schema.png")
connectionIcon = icon("connection.png")
tableIcon = icon("table.png")


class DataItemProvider(QgsDataItemProvider):
    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return "CartoProvider"

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parentItem):
        root = RootCollection()
        sip.transferto(root, None)
        return root


class RootCollection(QgsDataCollectionItem):

    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Carto", "/Carto")
        self.setIcon(cartoIcon)

    def createChildren(self):
        children = []
        connections = carto_connection.provider_connections()
        for connection in connections:
            item = ConnectionItem(self, connection)
            children.append(item)
        return children

    def actions(self, parent):
        actions = []
        if CartoApi.instance().is_logged_in():
            logout_action = QAction(QIcon(), "Log Out", parent)
            logout_action.triggered.connect(self.logout)
            actions.append(logout_action)
        else:
            login_action = QAction(QIcon(), "Log In...", parent)
            login_action.triggered.connect(self.open_login_dialog)
            actions.append(login_action)
        settings_action = QAction(QIcon(), "Settings...", parent)
        settings_action.triggered.connect(self.show_settings)
        actions.append(settings_action)
        return actions

    def show_settings(self):
        dlg = SettingsDialog()
        dlg.exec_()

    def logout(self):
        CartoApi.instance().logout()
        self.refreshConnections()

    def open_login_dialog(self):
        token = QgsSettings().value("carto/token", "")
        try:
            CartoApi.instance().login(token)
        except Exception as e:
            iface.messageBar().pushMessage(
                "Login failed",
                "Please check your token and try again",
                level=Qgis.Warning,
                duration=10,
            )
        else:
            iface.messageBar().pushMessage(
                "Login successful",
                "You are now logged in",
                level=Qgis.Success,
                duration=10,
            )
            self.refreshConnections()


class ConnectionItem(QgsDataCollectionItem):
    def __init__(self, parent, connection):
        QgsDataCollectionItem.__init__(
            self, parent, connection.name, "/Carto/connection" + connection.name
        )
        self.setIcon(connectionIcon)
        self.connection = connection

    def createChildren(self):
        children = []
        databases = self.connection.databases()
        for database in databases:
            item = DatabaseItem(self, database)
            children.append(item)
        return children

    def execute_sql(self):
        return
        """
        dialog = ExecuteSqlDialog(self)
        dialog.exec_()
        sql = dialog.sql
        if sql:
            CartoApi.instance().execute_query(self.connection.name, sql)
        """


class DatabaseItem(QgsDataCollectionItem):
    def __init__(self, parent, database):
        QgsDataCollectionItem.__init__(
            self, parent, database.name, "/Carto/database" + database.name
        )
        self.setIcon(databaseIcon)
        self.database = database

    def createChildren(self):
        children = []
        schemas = self.database.schemas()
        for schema in schemas:
            item = SchemaItem(self, schema)
            children.append(item)
        return children


class SchemaItem(QgsDataCollectionItem):
    def __init__(self, parent, schema):
        QgsDataCollectionItem.__init__(
            self, parent, schema.name, "/Carto/schema" + schema.name
        )
        self.setIcon(schemaIcon)
        self.schema = schema

    def createChildren(self):
        children = []
        tables = self.schema.tables()
        for table in tables:
            item = TableItem(self, table)
            sip.transferto(item, self)
            children.append(item)
        return children

    def actions(self, parent):
        actions = []

        import_action = QAction(QIcon(), "Import...", parent)
        import_action.triggered.connect(lambda: self.import_layer())
        actions.append(import_action)

        return actions

    def import_layer(self):
        dialog = ImportLayerDialog(self)
        dialog.exec_()
        if dialog.layer:
            layer = dialog.layer
            tablename = dialog.tablename
            fqn = (
                f"{self.schema.database.databaseid}.{self.schema.schemaid}.{tablename}"
            )
            layerfile = layer
            if isinstance(layer, QgsMapLayer):
                isSupported = True  # TODO
                if isSupported:
                    layerfile = layer.source()
                else:
                    # TODO
                    pass
            else:
                layerfile = layer
            try:
                CartoApi.instance().import_layer(
                    self.schema.database.connection.name, fqn, layerfile
                )
                QgsProject.instance().addMapLayer(layer)
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


class TableItem(QgsDataItem):
    def __init__(self, parent, table):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent, table.name, "/Carto/table/" + table.name
        )
        self.setIcon(tableIcon)
        self.populate()
        self.table = table

    def handleDoubleClick(self):
        return True

    def actions(self, parent):
        actions = []

        add_layer_action = QAction(QIcon(), "Add Layer", parent)
        add_layer_action.triggered.connect(lambda: self.add_layer())
        actions.append(add_layer_action)

        add_layer_filtered_action = QAction(
            QIcon(), "Add Layer Using Filter...", parent
        )
        add_layer_filtered_action.triggered.connect(lambda: self.add_layer_filtered())
        actions.append(add_layer_filtered_action)

        return actions

    def add_layer_filtered(self):
        dlg = DownloadFilteredLayerDialog(self)
        dlg.exec_()
        if dlg.accepted:
            where = dlg.where
            self._add_layer(where)

    def add_layer(self):
        self._add_layer(None)

    def _add_layer(self, where):
        layer = self.table.download(where)
        QgsProject.instance().addMapLayer(layer)
        if not self.table.schema.can_write():
            iface.messageBar().pushMessage(
                "Read-only",
                "No permission to write. Local changes will not be saved to the original table",
                level=Qgis.Warning,
                duration=10,
            )

        metadata = layer_metadata(layer)
        if not metadata["pk"]:
            iface.messageBar().pushMessage(
                "Missing PK",
                "The table has no PK defined. Local changes will not be saved to the original table",
                level=Qgis.Warning,
                duration=10,
            )
