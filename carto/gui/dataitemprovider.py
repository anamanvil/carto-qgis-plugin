import os
import sip
from json2html import json2html
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsDataItemProvider,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataProvider,
    QgsProject,
    Qgis,
    QgsVectorTileLayer,
    QgsMessageOutput,
    QgsApplication,
)
from qgis.utils import iface
from functools import partial

from carto.core.connection import CARTO_CONNECTION
from carto.core.layers import layer_metadata, save_layer_metadata
from carto.core.utils import MAX_ROWS
from carto.gui.importdialog import ImportDialog
from carto.gui.downloadfilteredlayerdialog import DownloadFilteredLayerDialog
from carto.gui.selectprimarykeydialog import SelectPrimaryKeyDialog
from carto.gui.authorization_manager import AUTHORIZATION_MANAGER
from carto.core.downloadtabletask import DownloadTableTask
from carto.gui.utils import icon


cartoIcon = icon("carto.svg")
databaseIcon = icon("folder.svg")
schemaIcon = icon("folder.svg")
bigqueryIcon = icon("bigquery.svg")
snowflakeIcon = icon("snowflake.svg")
redshiftIcon = icon("redshift.svg")
databricksIcon = icon("databricks.svg")
postgresIcon = icon("postgres.svg")
tableIcon = icon("table.svg")
basemapIcon = icon("basemap.svg")


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


BASEMAP_STYLES = {
    "Positron": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    "Dark Matter": "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    "Voyager": "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
}
BASEMAP_URL = (
    "https://tiles-a.basemaps.cartocdn.com/vectortiles/carto.streets/v1/{z}/{x}/{y}.mvt"
)


class BasemapsCollection(QgsDataCollectionItem):
    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Basemaps", "/Basemaps")
        self.setIcon(basemapIcon)

    def createChildren(self):
        children = []
        for name, url in BASEMAP_STYLES.items():
            item = BasemapItem(self, name, BASEMAP_URL, url)
            children.append(item)
        return children


class BasemapItem(QgsDataItem):
    def __init__(self, parent, name, url, style):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent, name, "Carto/basemaps/" + name
        )
        self.setIcon(basemapIcon)
        self.url = url
        self.style = style
        self.name = name
        self.populate()

    def handleDoubleClick(self):
        return True

    def actions(self, parent):
        actions = []

        add_layer_action = QAction(QIcon(), "Add Layer", parent)
        add_layer_action.triggered.connect(self.add_layer)
        actions.append(add_layer_action)

        return actions

    def add_layer(self):
        uri = f"styleUrl={self.style}&type=xyz&url={self.url}&zmax=14&zmin=0"
        layer = QgsVectorTileLayer(uri, self.name)
        layer.loadDefaultStyle()
        QgsProject.instance().addMapLayer(layer)


class ConnectionsItem(QgsDataCollectionItem):
    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Connections", "/Connections")
        self.setIcon(cartoIcon)
        self.populate()

    def createChildren(self):
        children = []
        connections = CARTO_CONNECTION.provider_connections()
        for connection in connections:
            item = ConnectionItem(self, connection)
            sip.transferto(item, self)
            children.append(item)
        return children


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
        elif "databricks" in connection.provider_type:
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
                dialog.file_or_layer,
                dialog.tablename,
            )
            dialog.schema.clear_tables_cache()


MAX_TABLE_SIZE = 50


class TableItem(QgsDataItem):
    def __init__(self, parent, table):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent, table.name, "/Carto/table/" + table.name
        )
        self.table = table
        self.tasks = []
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

    def _add_layer(self, where=None):
        where = where or f"TRUE LIMIT {MAX_ROWS}"

        task = DownloadTableTask(self.table, where)

        def _show_terminated_message():
            iface.messageBar().pushMessage(
                f"Layer download failed or was canceled ({self.table.name})",
                level=Qgis.Warning,
                duration=5,
            )

        task.taskTerminated.connect(_show_terminated_message)
        task.taskCompleted.connect(partial(self._add_to_project, task))

        self.tasks.append(task)

        QgsApplication.taskManager().addTask(task)
        QCoreApplication.processEvents()
        iface.messageBar().pushMessage(
            "",
            "Download task added to QGIS task manager",
            level=Qgis.Info,
            duration=5,
        )

    def _add_to_project(self, task):
        layer = task.layer
        if layer is None:
            iface.messageBar().pushMessage(
                "The query didn't yield any data to download",
                level=Qgis.Warning,
                duration=10,
            )
            return

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
        self.tasks.remove(task)


class RootCollection(QgsDataCollectionItem):

    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "CARTO", "/Carto/root")
        self.setIcon(cartoIcon)
        # CARTO_CONNECTION.connections_changed.connect(self.connectionsChanged)

    def createChildren(self):
        self.connectionsItem = ConnectionsItem()
        self.basemapsItem = BasemapsCollection()
        children = [self.connectionsItem, self.basemapsItem]
        return children

    def actions(self, parent):
        actions = [AUTHORIZATION_MANAGER.login_action]
        return actions
