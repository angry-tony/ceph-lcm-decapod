#!/bin/sh

mongo \
    --ssl \
    --sslAllowInvalidHostnames \
    --sslCAFile /certs/mongodb-ca.crt \
    "$@"
