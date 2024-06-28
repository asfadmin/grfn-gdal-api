#!/bin/bash

docker build -t packaging-image .
docker run --name packaging-container -itd packaging-image bash
docker cp packaging-container:/tmp/package.zip package.zip
docker stop packaging-container
docker rm packaging-container
