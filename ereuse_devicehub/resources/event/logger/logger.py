import json
from multiprocessing import Process, Queue

from eve.methods.post import post_internal
from flask import current_app as app
from flask import current_app, g
from pymongo.errors import DuplicateKeyError

from ereuse_devicehub.resources.account.user import Role
from ereuse_devicehub.utils import get_last_exception_info
from .grd_logger.grd_logger import GRDLogger


class Logger:
    """
    Generic class logger. Carries a long-running thread which contains the different logging mechanisms, and sends
    identifiers of events to the respective loggers.
    """
    queue = Queue()
    thread = None
    token = None

    @classmethod
    def log_event(cls, event_id: str, requested_database: str):
        """
        Logs an event.
        """
        if not cls.thread or not cls.thread.is_alive():
            cls._init()
        cls.queue.put((event_id, requested_database, app.config))

    @classmethod
    def _init(cls):
        """
        Prepares stuff, just needs to be executed at the beginning, once.
        """
        account = current_app.config['LOGGER_ACCOUNT']
        account.update({'role': Role.SUPERUSER})
        account['@type'] = 'Account'
        actual_mongo_prefix = g.mongo_prefix  # todo why can't I use current_app.get_mongo_prefix()?
        del g.mongo_prefix
        result = app.data.find_one_raw('accounts', {'email': account['email']})
        if result is None:
            try:
                post_internal('accounts', dict(account),
                              True)  # If we validate, RolesAuth._set_database will change our db
            except DuplicateKeyError:
                pass
        g.mongo_prefix = actual_mongo_prefix
        response = app.test_client().post('login', data=json.dumps(account), content_type='application/json')
        js = json.loads(response.data.decode())
        cls.token = js['token']
        cls.thread = Process(target=_loop, args=(cls.queue, cls.token))
        cls.thread.daemon = True
        cls.thread.start()


def _loop(queue: Queue, token: str):
    """
    Technically part of Logger, but outside of it for the system need. This method is in the child thread.

    It's a loop: It blocks waiting for events to log. When there is an event, it invokes the loggers. Starts again.
    :param queue:
    :return:
    """
    while True:
        event_id, requested_database, config = queue.get(True)  # We block ourselves waiting for something in the queue
        if config.get('GRD', True):
            try:
                GRDLogger(event_id, token, requested_database, config)
            except Exception as e:
                if not hasattr(e, 'ok'):
                    GRDLogger.logger.error(get_last_exception_info())
                raise e
