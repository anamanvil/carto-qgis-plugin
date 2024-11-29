import os
import json
from functools import partial

from qgis.utils import iface
from qgis.core import (
    Qgis,
    QgsVectorLayer,
    QgsApplication,
)

from qgis.PyQt.QtCore import Qt

from carto.core.api import CartoApi
from carto.core.logging import error
from carto.core.utils import (
    quote_for_provider,
    prepare_multipart_sql,
    prepare_geo_value_for_provider,
    prepare_num_string,
)
from carto.gui.utils import waitcursor


pluginPath = os.path.dirname(__file__)


def _f(f, *args):
    def wrapper():
        f(*args)

    return wrapper


class Changes(object):
    def __init__(self):
        self.geoms_changed = []
        self.attributes_changed = []
        self.features_removed = []
        self.features_added = []
        self.schema_has_changed = False


class LayerTracker:

    __instance = None

    @staticmethod
    def instance():
        if LayerTracker.__instance is None:
            LayerTracker()
        return LayerTracker.__instance

    def __init__(self):
        if LayerTracker.__instance is not None:
            raise Exception("Singleton class")

        LayerTracker.__instance = self

        self.connected = {}
        self.layer_changes = {}

    def layer_removed(self, layer):
        pass

    def layer_added(self, layer):
        if isinstance(layer, QgsVectorLayer):
            if is_carto_layer(layer):
                upload_changes_func = partial(self.upload_changes, layer)
                layer.afterCommitChanges.connect(upload_changes_func)
                before_commit_func = partial(self._before_commit, layer)
                layer.beforeCommitChanges.connect(before_commit_func)
                self.connected[layer.id()] = [upload_changes_func, before_commit_func]

    def schema_changed(self, layer, attrs):
        self.layer_changes[layer.id()].schema_has_changed = True

    def attributes_changed(self, layerid, values):
        self.layer_changes[layerid].attributes_changed = values

    def geoms_changed(self, layerid, geoms):
        self.layer_changes[layerid].geoms_changed = geoms

    def features_removed(self, layerid, features):
        self.layer_changes[layerid].features_removed = features

    def features_added(self, layerid, features):
        self.layer_changes[layerid].features_added = features

    def _before_commit(self, layer):
        self.layer_changes[layer.id()] = Changes()
        buffer = layer.editBuffer()
        buffer.committedAttributeValuesChanges.connect(self.attributes_changed)
        buffer.committedGeometriesChanges.connect(self.geoms_changed)
        buffer.committedFeaturesRemoved.connect(self.features_removed)
        buffer.committedFeaturesAdded.connect(self.features_added)
        schema_changed_func = partial(self.schema_changed, layer)
        buffer.committedAttributesAdded.connect(schema_changed_func)
        buffer.committedAttributesDeleted.connect(schema_changed_func)
        self.connected[layer.id()].append(schema_changed_func)

    @waitcursor
    def upload_changes(self, layer):
        if not can_write(layer):
            iface.messageBar().pushMessage(
                "No permission to write. Local changes will not be saved to the original table",
                level=Qgis.Warning,
                duration=5,
            )
            return
        metadata = layer_metadata(layer)

        if self.layer_changes[layer.id()].schema_has_changed:
            metadata["schema_changed"] = True
            save_layer_metadata(layer, metadata)

        if metadata["schema_changed"]:
            iface.messageBar().pushMessage(
                "Table schema has changed: changes will not be uploaded upstream",
                level=Qgis.Warning,
                duration=5,
            )
            return
        statements = []
        original_columns = [c["name"] for c in metadata["columns"]]
        pk_field = metadata["pk"]
        provider_type = metadata["provider_type"]
        geom_column = metadata["geom_column"]
        if not pk_field:
            iface.messageBar().pushMessage(
                "Layer has no Primary Key: changes will not be uploaded upstream",
                level=Qgis.Warning,
                duration=5,
            )
            return
        fqn = fqn_from_layer(layer)
        quoted_fqn = quote_for_provider(fqn, provider_type)
        geom_column = geom_column_from_layer(layer)
        if self.layer_changes[layer.id()].attributes_changed:
            for featureid, change in self.layer_changes[
                layer.id()
            ].attributes_changed.items():
                pk_value = layer.getFeature(featureid)[pk_field]
                for field_idx, value in change.items():
                    field = layer.fields().at(field_idx)
                    field_name = field.name()
                    value = (
                        prepare_num_string(value) if field.isNumeric() else f"'{value}'"
                    )
                    statements.append(
                        f"UPDATE {quoted_fqn} SET {field_name} = {value} WHERE {pk_field} = {pk_value};"
                    )
        if self.layer_changes[layer.id()].geoms_changed:
            for featureid, geom in self.layer_changes[layer.id()].geoms_changed.items():
                pk_value = layer.getFeature(featureid)[pk_field]
                geo_value = prepare_geo_value_for_provider(provider_type, geom)
                statements.append(
                    f"UPDATE {quoted_fqn} SET {geom_column} = {geo_value} WHERE {pk_field} = {pk_value};"
                )
        if self.layer_changes[layer.id()].features_removed:
            for featureid in self.layer_changes[layer.id()].features_removed:
                feature = layer.getFeature(featureid)
                pk_value = feature[pk_field]
                statements.append(
                    f"DELETE FROM {quoted_fqn} WHERE {pk_field} = {pk_value};"
                )
        if self.layer_changes[layer.id()].features_added:
            for feature in self.layer_changes[layer.id()].features_added:
                fields = []
                values = []
                if geom_column is not None:
                    geom = feature.geometry()
                    geo_value = prepare_geo_value_for_provider(provider_type, geom)
                    fields.append(geom_column)
                    values.append(geo_value)
                for i in range(feature.fields().count()):
                    field = feature.fields().at(i)
                    field_name = field.name()
                    if field_name in original_columns:
                        value = feature[field.name()]
                        value = (
                            prepare_num_string(value)
                            if field.isNumeric()
                            else f"'{value}'"
                        )
                        fields.append(field_name)
                        values.append(value)
                statements.append(
                    f"INSERT INTO {quoted_fqn} ({','.join(fields)}) VALUES ({','.join(values)});"
                )
        connection = connection_from_layer(layer)
        try:
            sql = prepare_multipart_sql(statements, provider_type, fqn)
            CartoApi.instance().execute_query(connection, sql)
            iface.messageBar().pushMessage(
                "Layer changes uploaded", level=Qgis.Success, duration=5
            )
        except Exception as e:
            iface.messageBar().pushMessage(
                "Error uploading changes: changes could not be made in the upstream table",
                level=Qgis.Critical,
                duration=5,
            )
            error("Error uploading changes: " + str(e))

    def disconnect_layer(self, layer):
        for f in self.connected[layer.id()]:
            layer.afterCommitChanges.disconnect(f)


def layers_folder():
    folder = os.path.join(
        os.path.dirname(QgsApplication.qgisUserDatabaseFilePath()), "cartolayers"
    )
    return folder


def filepath_for_table(connectionid, databaseid, schemaid, tableid):
    return os.path.join(
        layers_folder(), connectionid, databaseid, schemaid, tableid + ".gpkg"
    )


def is_carto_layer(layer):
    path = layer.source()
    return path.startswith(layers_folder())


def connection_from_layer(layer):
    path = os.path.dirname(layer.source())
    parts = path.split(os.path.sep)
    return parts[-3]


def tablename_from_layer(layer):
    path = os.path.dirname(layer.source())
    parts = path.split(os.path.sep)
    return parts[-1].split(".")[0]


def fqn_from_layer(layer):
    path = os.path.dirname(layer.source())
    parts = path.split(os.path.sep)
    tablename = os.path.splitext(os.path.basename(layer.source()))[0]
    return ".".join([parts[-2], parts[-1], tablename])


def metadata_file(layer):
    return layer.source().split("|")[0] + ".cartometadata"


def layer_metadata(layer):
    with open(metadata_file(layer), "r") as f:
        metadata = json.load(f)
    return metadata


def save_layer_metadata(layer, metadata):
    with open(metadata_file(layer), "w") as f:
        json.dump(metadata, f)


def was_schema_changed(layer):
    metadata = layer_metadata(layer)
    return metadata["schema_changed"]


def pk_from_layer(layer):
    metadata = layer_metadata(layer)
    return metadata["pk"]


def can_write(layer):
    metadata = layer_metadata(layer)
    return metadata["can_write"]


def geom_column_from_layer(layer):
    metadata = layer_metadata(layer)
    return metadata["geom_column"]


def provider_type_from_layer(layer):
    metadata = layer_metadata(layer)
    return metadata["provider_type"]
