import os
import json
from functools import partial

from qgis.utils import iface
from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsVectorLayer,
    QgsFeatureRequest,
    QgsRectangle,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsProject,
    QgsGeometry,
    QgsTextAnnotation,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsFillSymbol,
    QgsApplication,
)

from qgis.PyQt.QtCore import Qt

from carto.core.api import CartoApi


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
                attributes_changed_func = partial(self.attributes_changed, layer)
                layer.committedAttributeValuesChanges.connect(self.attributes_changed)
                geoms_changed_func = partial(self.geoms_changed, layer)
                layer.committedGeometriesChanges.connect(self.geoms_changed)
                features_removed_func = partial(self.features_removed, layer)
                layer.committedFeaturesRemoved.connect(features_removed_func)
                features_added_func = partial(self.features_added, layer)
                layer.committedFeaturesAdded.connect(features_added_func)
                upload_changes_func = partial(self.upload_changes, layer)
                layer.afterCommitChanges.connect(upload_changes_func)
                before_commit_func = partial(self._before_commit, layer)
                layer.beforeCommitChanges.connect(before_commit_func)
                self.connected[layer.id()] = [
                    upload_changes_func,
                    attributes_changed_func,
                    geoms_changed_func,
                    before_commit_func,
                    features_removed_func,
                    features_added_func,
                ]

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

    def upload_changes(self, layer):
        statements = []
        fqn = f"`{fqn_from_layer(layer)}`"
        pk_field = pk_from_layer(layer)
        if not pk_field:
            return
        print(pk_field)
        geom_column = geom_column_from_layer(layer)
        if self.layer_changes[layer.id()].attributes_changed:
            for featureid, change in self.layer_changes[
                layer.id()
            ].attributes_changed.items():
                pk_value = layer.getFeature(featureid)[pk_field]
                for field_idx, value in change.items():
                    field_name = layer.fields().at(field_idx).name()
                    statements.append(
                        f"UPDATE {fqn} SET {field_name} = {value} WHERE {pk_field} = {pk_value};"
                    )
        if self.layer_changes[layer.id()].geoms_changed:
            for featureid, geom in self.layer_changes[layer.id()].geoms_changed.items():
                pk_value = layer.getFeature(featureid)[pk_field]
                statements.append(
                    f"UPDATE {fqn} SET {geom_column} = ST_GEOGFROMWKB({geom.asWkb().toHex()}) WHERE {pk_field} = {pk_value};"
                )
        if self.layer_changes[layer.id()].features_removed:
            for featureid in self.layer_changes[layer.id()].features_removed:
                feature = layer.getFeature(featureid)
                pk_value = feature[pk_field]
                statements.append(f"DELETE FROM {fqn} WHERE {pk_field} = {pk_value};")
        print(self.layer_changes[layer.id()].features_added)
        if self.layer_changes[layer.id()].features_added:
            for feature in self.layer_changes[layer.id()].features_added:
                fields = []
                values = []
                for field, value in feature.items():
                    fields.append(field)
                    values.append(value)
                statements.append(
                    f"INSERT INTO {fqn} ({','.join(fields)}) VALUES ({','.join(values)});"
                )
        connection = connection_from_layer(layer)
        try:
            sql = "\n".join(statements)
            sql = f"""
                    BEGIN
                        {sql}
                    END;
                """
            CartoApi.instance().execute_query(connection, sql)
            iface.messageBar().pushMessage(
                "Layer changes uploaded", level=Qgis.Success, duration=5
            )
        except Exception as e:
            iface.messageBar().pushMessage(
                "Error uploading changes: " + str(e), level=Qgis.Critical, duration=5
            )

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
    return layer.source() + ".cartometadata"


def layer_metadata(layer):
    with open(metadata_file(layer), "r") as f:
        metadata = json.load(f)
    return metadata


def save_layer_metadata(layer, metadata):
    with open(metadata_file(layer), "w") as f:
        json.dump(metadata, f)


def pk_from_layer(layer):
    metadata = layer_metadata(layer)
    return metadata["pk"]


def geom_column_from_layer(layer):
    metadata = layer_metadata(layer)
    return metadata["geom_column"]
