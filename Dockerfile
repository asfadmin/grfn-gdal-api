FROM ghcr.io/lambgeo/lambda-gdal:3.8-python3.11

ENV INSTALL_DIR=/tmp/deployment_package
ENV PACKAGE_ZIP=/tmp/package.zip

RUN yum install -y zip

# Install python package and dependencies
COPY requirements-reformat.txt .
RUN python -m pip install --no-compile -r requirements-reformat.txt -t $INSTALL_DIR

COPY reformat/src $INSTALL_DIR

# Reduce size of the C libs
RUN cd $PREFIX && find lib -name \*.so\* -exec strip {} \;

# Add python code to the deployment package
RUN cd $INSTALL_DIR && zip -r9q $PACKAGE_ZIP *

# Add GDAL libs (in $PREFIX/lib $PREFIX/bin $PREFIX/share) to the deployment package
RUN cd $PREFIX && zip -r9q --symlinks $PACKAGE_ZIP lib/*.so* share
RUN cd $PREFIX && zip -r9q --symlinks $PACKAGE_ZIP bin/gdal* bin/ogr* bin/geos* bin/nearblack
