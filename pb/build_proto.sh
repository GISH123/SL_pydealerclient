#!/bin/bash

protoc -I=./ --go_out=./ivi commu.proto
echo convert commu.proto success
protoc --go_out=plugins=grpc:./api api.proto
echo convert db.proto success

