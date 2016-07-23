import random
import string

from flask import current_app as app
from passlib.handlers.sha2_crypt import sha256_crypt

from ereuse_devicehub.resources.account.user import User, Role
from ereuse_devicehub.resources.event.device import DeviceEventDomain
from ereuse_devicehub.rest import execute_post


def hash_password(accounts: list):
    for account in accounts:
        if account['active']:
            account['password'] = sha256_crypt.encrypt(account['password'])


def add_token(documents: list):
    for document in documents:
        token = generate_token()
        while app.data.find_one_raw('accounts', {'token': token}) is not None:
            token = generate_token()
        document["token"] = token


def generate_token() -> str:
    return (''.join(random.choice(string.ascii_uppercase)
                    for x in range(10)))


# noinspection PyPep8Naming
def set_byUser(resource_name: str, items: list):
    if 'byUser' in app.config['DOMAIN'][resource_name]['schema']:
        for item in items:
            item['byUser'] = User.actual['_id']


# noinspection PyPep8Naming
def set_byOrganization(resource_name: str, items: list):
    """
    Sets the 'byOrganization' field, which is the materialization of the organization of byUser (the actual user).
    This materialization shall no be updated when the user's organization changes.
    """
    for item in items:
        if 'byOrganization' in app.config['DOMAIN'][resource_name]['schema']:
            if 'organization' in User.actual:
                item['byOrganization'] = User.actual['organization']


def set_default_database_if_empty(accounts: list):
    for account in accounts:
        if 'defaultDatabase' not in account and account['role'] != Role.SUPERUSER:
            account['defaultDatabase'] = account['databases'][0]


def add_or_get_inactive_account(events: list):
    # todo if register we need to make sure that user does not add the account again another time (usability?)
    for event in events:
        if event['@type'] == DeviceEventDomain.new_type('Receive'):
            _add_or_get_inactive_account_id(event, 'unregisteredReceiver', 'receiver')
        elif event['@type'] == DeviceEventDomain.new_type('Allocate'):
            _add_or_get_inactive_account_id(event, 'unregisteredTo', 'to')


def _add_or_get_inactive_account_id(event, field_name, recipient_field_name):
    if field_name in event:
        try:
            # We look for just accounts that share our database
            _id = app.data.find_one_raw('accounts',
                                        {
                                            'email': event[field_name]['email'],
                                            'databases': {'$in': User.actual['databases']}
                                        }
                                        )['_id']
        except TypeError:  # No account
            event[field_name]['databases'] = User.actual['databases']
            event[field_name]['active'] = False
            _id = execute_post('accounts', event[field_name])['_id']
        event[recipient_field_name] = _id
        del event[field_name]
