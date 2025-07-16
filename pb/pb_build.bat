@ECHO OFF

protoc -I=./ --python_out=../ commu.proto
ECHO convert commu.proto success
pause