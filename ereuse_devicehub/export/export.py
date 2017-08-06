from collections import defaultdict, OrderedDict, Iterator
from contextlib import suppress
from datetime import timedelta

import flask_excel as excel
from eve.auth import requires_auth
from flask import request
from inflection import humanize
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from pydash import keys
from pydash import map_
from pydash import py_
from pyexcel_webio import FILE_TYPE_MIME_TABLE as REVERSED_FILE_TYPE_MIME_TABLE
from werkzeug.exceptions import NotAcceptable

from ereuse_devicehub.header_cache import header_cache
from ereuse_devicehub.resources.account.domain import AccountDomain
from ereuse_devicehub.resources.device.component.settings import Component
from ereuse_devicehub.resources.device.domain import DeviceDomain
from ereuse_devicehub.resources.group.domain import GroupDomain
from ereuse_devicehub.resources.group.settings import Group
from ereuse_devicehub.resources.submitter.translator import Translator
from ereuse_devicehub.rest import execute_get

FILE_TYPE_MIME_TABLE = dict(zip(REVERSED_FILE_TYPE_MIME_TABLE.values(), REVERSED_FILE_TYPE_MIME_TABLE.keys()))


@header_cache(expires=10)
@requires_auth('resource')
def export(db, resource):
    """
    Exports devices as spreadsheets.
    See the docs in other-endpoints.rst
    """
    try:
        file_type = FILE_TYPE_MIME_TABLE[request.accept_mimetypes.best]
    except KeyError:
        raise NotAcceptable()
    ids = request.args.getlist('ids')  # Returns empty list by default
    token = AccountDomain.hash_token(AccountDomain.actual_token)
    translator = SpreadsheetTranslator(request.args.get('type', 'detailed') == 'brief')
    spreadsheets = OrderedDict()
    if resource in Group.resource_names:
        domain = GroupDomain.children_resources[resource]
        f = py_().select(lambda d: d['@type'] not in Component.types and not d.get('placeholder', False))
        # ids are groups and we want their inner devices, each of them in a page:
        # page1 is group1 and contains its devices, page2 is group2 and contains its devices, and so on
        for _id in ids:
            group = domain.get_one(_id)
            # Let's get the full devices and their components with embedded stuff
            devices = f(domain.get_descendants(DeviceDomain, _id))
            devices_with_components = map(lambda device: get_components(device, db, token), devices)
            spreadsheets[group.get('label', group['_id'])] = translator.translate(devices_with_components)
    else:
        # Let's get the full devices and their components with embedded stuff
        QUERY = {'@type': {'$nin': Component.types}}
        devices = DeviceDomain.get_in('_id', ids, False) if ids else DeviceDomain.get(QUERY, False)
        devices_with_components = map(lambda device: get_components(device, db, token), devices)
        spreadsheets['Devices'] = translator.translate(devices_with_components)
    return excel.make_response_from_book_dict(spreadsheets, file_type, file_name=resource)


def get_components(device, db, token) -> dict:
    """
    Get the passed-in components with their tests and erasures embedded
    :return The device
    """
    if not device['components']:
        return device
    params = {
        'where': {'_id': {'$in': device['components']}},
        'embedded': {'tests': 1, 'erasures': 1}
    }
    device['components'] = execute_get(db + '/devices', token, params=params)['_items']
    return device


class SpreadsheetTranslator(Translator):
    """Translates a set of devices into a dict for flask-excel representing a spreadsheet"""

    def __init__(self, brief: bool):
        # Definition of the dictionary used to translate
        self.brief = brief
        p = py_()
        d = OrderedDict()  # we want ordered dict as in translate we want to preserve this order in the spreadsheet
        d['Identifier'] = p.get('_id')
        d['type'] = p.get('@type')
        if not brief:
            d['Label ID'] = p.get('labelId')
            d['Giver ID'] = p.get('gid')
            d['Refurbisher ID'] = p.get('rid')
            d['Serial Number'] = p.get('serialNumber')
        d['Model'] = p.get('model')
        d['Manufacturer'] = p.get('manufacturer')
        d['State'] = p.get('events').first().pick('@type', 'label').implode(' ')
        if not brief:
            d['Registered in'] = p.get('_created')
        d['Processor'] = p.get('processorModel')
        d['RAM (GB)'] = p.get('totalRamSize').floor()
        d['HDD (MB)'] = p.get('totalHardDriveSize').floor()
        # Note that in translate_one we translate 'components'
        super().__init__(d)

    def translate_one(self, device: dict) -> dict:
        translated = super().translate_one(device)
        # Avoid exception in openpyxl/cell/cell.py line 156 for using illegal characters
        for key, value in translated.items():
            if type(value) is str:
                if next(ILLEGAL_CHARACTERS_RE.finditer(value), None):
                    translated[key] = '**'
        # Component translation
        # Let's decompose components so we get ComponentTypeA 1: ..., ComponentTypeA 2: ...
        pick = py_().pick(([] if self.brief else ['_id', 'serialNumber']) + ['model', 'manufacturer']).implode(' ')
        # For david
        counter_each_type = defaultdict(int)
        for pos, component in enumerate(device['components']):
            _type = device['components'][pos]['@type']
            count = counter_each_type[_type] = counter_each_type[_type] + 1
            header = '{} {}'.format(_type, count)
            translated[header + ' system id'] = component.get('_id', '')
            translated[header + ' serial number'] = component.get('serialNumber', '')
            translated[header + ' model'] = component.get('model', '')
            translated[header + ' manufacturer'] = component.get('manufacturer', '')
            if not self.brief or _type not in {'Motherboard', 'RamModule', 'Processor'}:
                translated[header] = pick(component)
                if _type == 'HardDrive':
                    with suppress(KeyError):
                        erasure = component['erasures'][0]
                        t = '{} {}'.format('Successful' if erasure['success'] else 'Failed', humanize(erasure['@type']))
                        translated[header + ' erasure'] = t
                    with suppress(KeyError):
                        lifetime = round(timedelta(hours=component['tests'][0]['lifetime']).days / 365, 2)
                        translated[header + ' lifetime (years)'] = lifetime
                        translated[header + ' test result'] = component['tests'][0]['status']
                        # For david
                        translated[header + ' lifetime (hours)'] = component['tests'][0]['lifetime']
                        translated[header + ' reading speed'] = component['benchmarks'][0]['readingSpeed']
                        translated[header + ' writing speed'] = component['benchmarks'][0]['writingSpeed']
                elif _type == 'Processor':
                    with suppress(KeyError):
                        translated[header + ' number of cores'] = component['numberOfCores']
                    with suppress(KeyError):
                        translated[header + ' score'] = component['benchmarks'][0]['score']
                elif _type == 'RamModule':
                    for field in 'size', 'speed':
                        with suppress(KeyError):
                            translated[header + ' ' + field] = component[field]
        if 'Registered in' in translated:
            translated['Registered in'] = str(translated['Registered in'])
        return translated

    def translate(self, devices: Iterator) -> list:
        """Translates a spreadsheet, which is a table of resources as rows plus the field names as header."""
        translated = super().translate(devices)
        # Let's transform the dict to a table-like array
        # Generation of table headers
        field_names = list(self.dict.keys())  # We want first the keys we set in the translation dict
        field_names += py_(translated).map(keys).flatten().uniq().difference(field_names).sort().value()
        # compute the rows; header titles + fields (note we do not use pick as we don't want None but '' for empty)
        return [field_names] + map_(translated, lambda res: [res.get(f, '') or '' for f in field_names])
