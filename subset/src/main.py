from osgeo import gdal
from os import getenv, basename
import json
from logging import getLogger
import boto3


log = getLogger()
log.setLevel('INFO')
config = json.loads(getenv('CONFIG'))


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


def lambda_handler(event, context):
    parms = event['queryStringParameters']
    output_key = basename(parms['product'])
    vsi_file = '/vsimem/image.tif'
    ds = gdal.Open('/vsizip/vsicurl/https://hyp3-download.asf.alaska.edu/data/' + parms['product'])
    ds.BuildOverviews("NEAREST", [2,4,8,16,32])
    ds2 = gdal.Translate(vsi_file, ds, projWin=[parms['ulx'], parms['uly'], parms['lrx'], parms['lry']], creationOptions = ['COMPRESS=DEFLATE','TILED=YES','COPY_SRC_OVERVIEWS=YES'])
    ds2 = None
    try:
        vsimem_file = SimpleVSIMEMFile(vsi_file)
        s3 = boto3.resource('s3')
        obj = s3.Object(bucket_name=config['bucket'], key=output_key)
        obj.put(Body=vsimem_file)
    finally:
        vsimem_file = None
    response = {
        'statusCode': 307,
        'headers': {
            'Location': 'https://s3.amazonaws.com/{0}/{1}'.format(config['bucket'], output_key),
        },
        'body': None,
    }
    return response
