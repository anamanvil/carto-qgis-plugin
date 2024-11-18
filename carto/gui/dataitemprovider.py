import os
import sip
from json2html import json2html
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog
from qgis.core import (
    QgsDataItemProvider,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataProvider,
    QgsProject,
    QgsSettings,
    Qgis,
    QgsMapLayer,
    QgsMessageOutput,
)
from qgis.utils import iface

from carto.core.connection import CartoConnection
from carto.core.api import CartoApi
from carto.core.layers import layer_metadata, save_layer_metadata
from carto.core.utils import setting, TOKEN
from carto.gui.settingsdialog import SettingsDialog
from carto.gui.importdialog import ImportDialog
from carto.gui.downloadfilteredlayerdialog import DownloadFilteredLayerDialog
from carto.gui.selectprimarykeydialog import SelectPrimaryKeyDialog

IMGS_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "imgs")

carto_connection = CartoConnection()

pluginPath = os.path.dirname(__file__)


def icon(f):
    return QIcon(os.path.join(pluginPath, "img", f))


cartoIcon = icon("carto.svg")
databaseIcon = icon("folder.svg")
schemaIcon = icon("folder.svg")
bigqueryIcon = icon("bigquery.svg")
snowflakeIcon = icon("snowflake.svg")
redshiftIcon = icon("redshift.svg")
databricksIcon = icon("databricks.svg")
postgresIcon = icon("postgres.svg")
tableIcon = icon("table.svg")


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
        QgsDataCollectionItem.__init__(self, None, "CARTO", "/Carto")
        self.setIcon(cartoIcon)
        CartoConnection.instance().connections_changed.connect(self.refreshConnections)

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
            login_action.triggered.connect(self.login)
            actions.append(login_action)
        settings_action = QAction(QIcon(), "Settings...", parent)
        settings_action.triggered.connect(self.show_settings)
        actions.append(settings_action)
        return actions

    def show_settings(self):
        dlg = SettingsDialog(iface.mainWindow())
        dlg.exec_()

    def logout(self):
        CartoApi.instance().logout()

    def login(self):
        CartoApi.instance().login()


class ConnectionItem(QgsDataCollectionItem):
    def __init__(self, parent, connection):
        QgsDataCollectionItem.__init__(
            self, parent, connection.name, "/Carto/connection" + connection.name
        )
        if connection.provider_type == "bigquery":
            self.setIcon(bigqueryIcon)
        elif connection.provider_type == "snowflake":
            self.setIcon(snowflakeIcon)
        elif connection.provider_type == "redshift":
            self.setIcon(redshiftIcon)
        elif connection.provider_type == "databricks":
            self.setIcon(databricksIcon)
        elif connection.provider_type == "postgres":
            self.setIcon(postgresIcon)
        else:
            self.setIcon(cartoIcon)
        self.connection = connection

    def createChildren(self):
        children = []
        databases = self.connection.databases()
        for database in databases:
            item = DatabaseItem(self, database)
            children.append(item)
        return children


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
        import_action.triggered.connect(self.import_layer)
        actions.append(import_action)

        return actions

    def import_layer(self):
        dialog = ImportDialog(
            self.schema.database.connection,
            self.schema.database,
            self.schema,
            iface.mainWindow(),
        )
        ret = dialog.exec_()
        if ret == QDialog.Accepted:
            dialog.schema.import_table(
                dialog.layer_or_file,
                dialog.tablename,
            )


MAX_TABLE_SIZE = 10


class TableItem(QgsDataItem):
    def __init__(self, parent, table):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent, table.name, "/Carto/table/" + table.name
        )
        self.table = table
        self.setIcon(tableIcon)
        self.populate()

    def handleDoubleClick(self):
        return True

    def actions(self, parent):
        actions = []

        add_layer_action = QAction(QIcon(), "Add Layer", parent)
        add_layer_action.triggered.connect(self.add_layer)
        add_layer_action.setEnabled(self.table.size < MAX_TABLE_SIZE)
        actions.append(add_layer_action)

        add_layer_filtered_action = QAction(
            QIcon(), "Add Layer Using Filter...", parent
        )
        add_layer_filtered_action.triggered.connect(self.add_layer_filtered)
        actions.append(add_layer_filtered_action)

        table_info_action = QAction(QIcon(), "Table Info...", parent)
        table_info_action.triggered.connect(self.table_info_action)
        actions.append(table_info_action)

        return actions

    def table_info_action(self):
        metadata = self.table.table_info()
        html = json2html.convert(json=metadata)
        dlg = QgsMessageOutput.createMessageOutput()
        dlg.setTitle("Table info")
        dlg.setMessage(html, QgsMessageOutput.MessageHtml)
        dlg.showMessage()

    def add_layer_filtered(self):
        dlg = DownloadFilteredLayerDialog(self.table)
        dlg.show()
        ret = dlg.exec_()
        if ret == QDialog.Accepted:
            self._add_layer(dlg.where)

    def add_layer(self):
        self._add_layer(None)

    def _add_layer(self, where):
        layer = self.table.download(where)
        QgsProject.instance().addMapLayer(layer)
        metadata = layer_metadata(layer)
        if not metadata["can_write"]:
            iface.messageBar().pushMessage(
                "Read-only",
                "No permission to write. Local changes will not be saved to the original table",
                level=Qgis.Warning,
                duration=10,
            )
            return

        if not metadata["pk"]:
            columns = [c["name"] for c in metadata["columns"]]
            dialog = SelectPrimaryKeyDialog(columns)
            dialog.exec_()
            if dialog.pk:
                metadata["pk"] = dialog.pk
                save_layer_metadata(layer, metadata)
            else:
                iface.messageBar().pushMessage(
                    "Missing PK",
                    "The table has no PK defined. Local changes will not be saved to the original table",
                    level=Qgis.Warning,
                    duration=10,
                )
