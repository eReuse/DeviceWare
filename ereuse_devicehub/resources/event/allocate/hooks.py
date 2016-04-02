from ereuse_devicehub.resources.account.user import User
from ereuse_devicehub.resources.device.device import Device
from ereuse_devicehub.resources.event.deallocate.deallocate import AlreadyAllocated


def materialize_actual_owners_add(allocates: list):
    for allocate in allocates:
        properties = {'$addToSet': {'owners': allocate['to']}}
        Device.update(allocate['devices'], properties)
        Device.update(allocate.get('components', []), properties)


def avoid_repeating_allocations(allocates: list):
    """
    Checks that we are not allocating to an account that is already an owner of the device

    This method must execute after
    :param allocates:
    :return:
    """
    for allocate in allocates:
        devices_with_repeating_owners = Device.get_many({
            '$or': [
                {'_id': {'$in': [allocate['devices']]}},
                {'owners': {'$in': [allocate['to']]}}
            ]
        })
        ids = [device['_id'] for device in devices_with_repeating_owners]
        allocate['devices'] = list(set(allocate['devices']) - set(ids))
        if len(allocate['devices']) == 0:
            raise AlreadyAllocated()


def set_organization(allocates: list):
    for allocate in allocates:
        org = User.get(allocate['to']).get('organization')
        if org is not None:
            allocate['toOrganization'] = org
