from os import getenv
import json
from logging import getLogger

log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))


def lambda_handler(event, context):
    log.info('hello world')
