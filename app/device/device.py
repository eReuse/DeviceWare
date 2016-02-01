from bson import objectid, ObjectId
from eve.utils import document_etag
from flask import g

from app.app import app
from app.device.component.component import Component
from app.device.exceptions import DeviceNotFound
from app.exceptions import InnerRequestError
from app.utils import get_resource_name
from app.rest import execute_get


class Device:
    @staticmethod
    def get(identifier: str or int) -> dict:
        """
        Gets a single device.
        :param identifier: hid or _id
        :return:
        """
        try:
            device = execute_get(app.auth.get_requested_database_for_uri() + 'devices/' + str(identifier))
        except InnerRequestError as e:
            if e.status_code == 404:
                raise DeviceNotFound()
        else:
            return device

    @staticmethod
    def get_by_pid(pid: str) -> dict:
        """
        Gets a single device, using the pid.
        :param pid:
        :return:
        """
        try:
            device = execute_get(app.auth.get_requested_database_for_uri() + 'devices?where={"pid":"' + pid + '"}')[0]
        except KeyError:
            raise DeviceNotFound()
        else:
            return device

    @staticmethod
    def get_parent(_id: str) -> dict or None:
        parent = app.data.driver.db['devices'].find_one({'components': {'$in': [_id]}})
        if parent is None:
            raise DeviceNotFound()
        else:
            return parent

    @staticmethod
    def get_similar_component(component: dict, parent_id: str) -> dict:
        # We the unsecured _id of the devices of all parent_id snapshots
        snapshots = list(app.data.driver.db['events'].find({'@type': 'Snapshot', 'device': parent_id}))
        devices_id = set()
        for snapshot in snapshots:
            for unsecured in snapshot['unsecured']:
                devices_id.add(unsecured['_id'])
        # We get the devices whose _id and etag matches
        etag = Device.generate_etag(component)
        query = {'_id': {'$in': list(devices_id)}, '_etag': etag}
        device = app.data.driver.db['devices'].find_one(query)
        if device is None:
            raise DeviceNotFound()
        else:
            return Device.get(device['_id'])  # todo if we materialize components we do not need to do double query

    @staticmethod
    def generate_etag(device: dict) -> str:
        return document_etag(device, app.config['DOMAIN'][get_resource_name(device['@type'])]['etag_ignore_fields'])

    @staticmethod
    def seem_equal(x: dict, y: dict) -> bool:
        x_tag = x['_etag'] if '_etag' in x else Device.generate_etag(x)
        y_tag = y['_etag'] if '_etag' in y else Device.generate_etag(y)
        return x_tag == y_tag

    @staticmethod
    def difference(list_to_remove_devices_from, checking_list):
        """
        Computes the difference between two lists of devices.

        To compute the difference the position of the parameters is important
        :param list_to_remove_devices_from:
        :param checking_list:
        :return:
        """
        difference = []
        for x in list_to_remove_devices_from:
            found = False
            for y in checking_list:
                if Device.seem_equal(x, y):
                    found = True
            if not found:
                difference.append(x)
        return difference

    @staticmethod
    def get_types():
        return Component.get_types_of_components() + ('Peripheral', 'Monitor', 'Mobile', 'Computer')

    @staticmethod
    def resource_types():
        return (get_resource_name(event) for event in Device.get_types())

    @staticmethod
    def get_components(devices_id: list):
        return list(app.data.driver.db['devices'].find({'_id': {'$in': devices_id}}, {'components': True}))

    def get_components_in_set(devices_id: list):
        components = set()
        for device in Device.get_components(list(devices_id)):
            if 'components' in device:
                components |= set(device['components'])
        return components
