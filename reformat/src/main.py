from osgeo import gdal
from os import path, getenv, chmod
import json
from logging import getLogger
from uuid import uuid4
import boto3


log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))
s3 = boto3.resource('s3')
secrets_manager = boto3.client('secretsmanager')


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


def get_output_key(product,layer):
    prefix = uuid4()
    basename = path.basename(product)
    basename_without_extension = path.splitext(basename)[0]
    layer_name = path.basename(layer)
    output_key = '{0}/{1}_{2}.tif'.format(prefix, basename_without_extension,layer_name)
    return output_key


def lambda_handler(event, context):
    log.info(gdal.__version__)
    parms = event['queryStringParameters']
    output_key = get_output_key(parms['product'],parms['layer'])
    vsi_file = '/vsimem/image.tif'
    input_ds = "NETCDF:\"" + config['product_path'] + parms['product'] + "\"://" + parms['layer']
    log.info(input_ds)
    ds = gdal.Open(input_ds)
    projection   = ds.GetProjection()
    geotransform = ds.GetGeoTransform()
    log.info("Proj/Geo: " +  str(projection) + " " +  str(geotransform))
    ds2 = gdal.Translate(
        destName=vsi_file,
        srcDS=ds,
        creationOptions=['COMPRESS=DEFLATE', 'TILED=YES', 'COPY_SRC_OVERVIEWS=YES']
    )
    ds2 = None
    try:
        vsimem_file = SimpleVSIMEMFile(vsi_file)
        obj = s3.Object(bucket_name=config['bucket'], key=output_key)
        obj.put(Body=vsimem_file)
    finally:
        gdal.Unlink(vsi_file)
    response = {
        'statusCode': 307,
        'headers': {
            'Location': 'https://s3.amazonaws.com/{0}/{1}'.format(config['bucket'], output_key),
        },
        'body': None,
    }
    return response

