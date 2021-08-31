from osgeo import gdal
from os import path, getenv, chmod, remove
import json
from logging import getLogger
from urllib.parse import urljoin, urlparse
from uuid import uuid4
import boto3
from requests import Session


log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))
s3 = boto3.resource('s3')
secrets_manager = boto3.client('secretsmanager')
session = Session()


def get_secret(secret_arn):
    response = secrets_manager.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response['SecretString'])
    return secret


def write_content_to_netrc_file(netrc_content):
    netrc_file = path.join(getenv('HOME'), '.netrc')
    with open(netrc_file, 'w') as f:
        f.write(netrc_content)
    chmod(netrc_file, 0o600)


def set_up_netrc(secret_arn):
    netrc_content = get_secret(secret_arn)['netrc_content']
    write_content_to_netrc_file(netrc_content)


set_up_netrc(config['secret_arn'])


class SimpleVSIMemFileError(Exception):
    """Unknown SimpleVSIMemFile error with VSI subsystem."""


class SimpleVSIMEMFile(object):
    def __init__(self, path):
        """Simple file-like object for reading out of a VSIMEM dataset.
        Params:
            path: /vsimem path to use
        """
        self._path = path
        self._size = gdal.VSIStatL(self._path).size
        self._check_error()
        self._pos = 0

    def __len__(self):
        """Length of the file."""
        return self._size

    def read(self, size=-1):
        """Read size bytes from the file.
        Params:
            size: Number of bytes to read.
        """

        length = len(self)
        if self._pos >= length:
            # No more data to read
            return b""

        if size == -1:
            # Set size to remainder of file
            size = length - self._pos
        else:
            # Limit size to remainder of file
            size = min(size, length - self._pos)

        # Open file
        vsif = gdal.VSIFOpenL(self._path, "r")
        self._check_error()
        try:
            # Seek to current position, read data, and update position
            gdal.VSIFSeekL(vsif, self._pos, 0)
            self._check_error()
            buf = gdal.VSIFReadL(1, size, vsif)
            self._check_error()
            self._pos += len(buf)

        finally:
            # Close file
            gdal.VSIFCloseL(vsif)
            self._check_error()

        return buf

    def seek(self, offset, whence=0):
        """Seek to position in file."""
        if whence == 0:
            # Seek from start of file
            self._pos = min(offset, len(self))
        elif whence == 1:
            # Seek from current position
            self._pos = min(max(0, self._pos + offset), len(self))
        elif whence == 2:
            # Seek from end of file
            self._pos = max(0, len(self) - offset)
        return self._pos

    def tell(self):
        """Tell current position in file."""
        return self._pos

    def _check_error(self):
        if gdal.VSIGetLastErrorNo() != 0:
            raise SimpleVSIMemFileError(gdal.VSIGetLastErrorMsg())


def get_output_key(product, layer):
    prefix = uuid4()
    product_basename = path.basename(product)
    product_basename_without_extension = path.splitext(product_basename)[0]
    layer_basename = path.basename(layer)
    output_key = '{0}/{1}-{2}.tif'.format(prefix, product_basename_without_extension, layer_basename)
    return output_key


def download_file(host_url, product):
    download_url = urljoin(host_url, product)
    response = session.get(download_url)
    response.raise_for_status()
    file_name = path.join('/tmp', product)
    with open(file_name, 'wb') as f:
        for block in response.iter_content(1024):
            f.write(block)
    return file_name


def get_redirect_response(bucket, key):
    return {
        'statusCode': 307,
        'headers': {
            'Location': 'https://s3.amazonaws.com/{0}/{1}'.format(bucket, key),
        },
        'body': None,
    }


def translate_netcdf_to_geotiff(input_datasource, output_datasource):
    handle = gdal.Open(input_datasource)
    gdal.Translate(
        destName=output_datasource,
        srcDS=handle,
        creationOptions=['COMPRESS=DEFLATE', 'TILED=YES', 'COPY_SRC_OVERVIEWS=YES']
    )
    handle = None


def upload_vsimem_to_s3(vsimem_datasource, bucket, key):
    vsimem_file = SimpleVSIMEMFile(vsimem_datasource)
    obj = s3.Object(bucket_name=bucket, key=key)
    obj.put(Body=vsimem_file)


def get_cors_headers(origin):
    url_parsed = urlparse(origin)
    if url_parsed.netloc.endswith('asf.alaska.edu') and url_parsed.scheme == 'https':
        return {
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
        }
    return {}


def lambda_handler(event, context):
    parms = event['queryStringParameters']

    input_file_name = download_file(config['product_path'], parms['product'])

    input_datasource = 'NETCDF:"{0}"://{1}'.format(input_file_name, parms['layer'])
    vsimem_datasource = '/vsimem/image.tif'
    try:
        translate_netcdf_to_geotiff(input_datasource, vsimem_datasource)
    finally:
        remove(input_file_name)

    output_key = get_output_key(parms['product'], parms['layer'])
    try:
        upload_vsimem_to_s3(vsimem_datasource, config['bucket'], output_key)
    finally:
        gdal.Unlink(vsimem_datasource)

    response = get_redirect_response(config['bucket'], output_key)
    cors_headers = get_cors_headers(context['headers'].get('Origin'))
    response['headers'].update(cors_headers)
    return response
