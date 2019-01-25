from os import getenv
import json
from logging import getLogger

log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))


def lambda_handler(event, context):
    log.info(event)
    response = {
      'statusCode': 200,
      'body': 'hello world!',
    }
    return response
