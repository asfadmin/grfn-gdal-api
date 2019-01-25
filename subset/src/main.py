from os import getenv
import json
from logging import getLogger

log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))


def lambda_handler(event, context):
    log.info(event)
    response = {
      'statusCode': 307,
      'headers': {
        'Location': 'https://www.asf.alaska.edu/',
      }
      'body': None,
    }
    return response
