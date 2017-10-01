import json
from io import BytesIO

from assertpy import assert_that
from passlib.handlers.sha2_crypt import sha256_crypt
from pydash import map_values

from ereuse_devicehub.resources.account.role import Role
from ereuse_devicehub.security.perms import ACCESS, READ
from ereuse_devicehub.tests import TestBase
from ereuse_devicehub.tests.test_resources.test_events.test_device_event import TestDeviceEvent


class TestSell(TestDeviceEvent):
    def setUp(self, settings_file=None, url_converters=None):
        super().setUp(settings_file, url_converters)
        self.db.accounts.insert_one(
            {
                'email': 'b@b.b',
                'password': sha256_crypt.hash('1234'),
                'role': Role.ADMIN,
                'token': 'TOKENB',
                'databases': {self.app.config['DATABASES'][1]: ACCESS},
                'defaultDatabase': self.app.config['DATABASES'][1],
                '@type': 'Account'
            }
        )
        self.account2 = self.login('b@b.b', '1234')
        self.token2 = self.account2['token']

    def test_sell_after_reserving(self):
        """
        Performs Sell in a group, referencing a Reserve and attaching two invoices.
        """
        # A second account with access to a lot reserves its devices
        lot = self.get_fixture(self.LOTS, 'lot')
        lot['children'] = {'devices': self.devices_id}
        lot['perms'] = [{'account': self.account2['_id'], 'perm': READ}]
        self.post_201(self.LOTS, lot)
        reserve = {'@type': 'devices:Reserve', 'devices': self.devices_id}
        reserve = self.post_201(self.DEVICE_EVENT_RESERVE, reserve, token=self.token2)

        # The first account performs sell
        first_pdf = b'pdf1'
        second_pdf = b'pdf2'
        sell = {
            '@type': 'devices:Sell',
            'devices': self.devices_id,
            'reserve': reserve['_id'],
            'to': self.account2['_id']
        }
        sell = map_values(sell, lambda x: json.dumps(x))
        sell['invoices'] = [(BytesIO(first_pdf), 'pdf1.pdf'), (BytesIO(second_pdf), 'pdf2.pdf')]
        with self.app.mail.record_messages() as outbox:
            sell = self.post_201(self.DEVICE_EVENT_SELL, sell, content_type='multipart/form-data')
            sell = self.get_200(self.EVENTS, item=sell['_id'])
            assert_that(sell).has_reserve(reserve['_id'])
            # The second account gets notified
            assert_that(outbox[0]).has_recipients(['b@b.b'])

            # The first account accesses the pdfs
            assert_that(sell).contains('invoices')
            assert_that(sell['invoices']).is_length(2)
            # First PDF
            pdf = self.get_200(sell['invoices'][0]['file'][1:])  # we remove the first '/'
            assert_that(pdf).is_equal_to(first_pdf)
            pdf = self.get_200(sell['invoices'][1]['file'][1:])
            assert_that(pdf).is_equal_to(second_pdf)
