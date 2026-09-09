# echo client program

import socket

HOST = '' # remote host
PORT = 50007 # same port used by server
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT)) # connects to a socket having same host ip and port. the default ip when nothing is mentioned is localhost 127.0.0.1, so it can only connect to local sockets.
    s.sendall(b'Hello World') # b is used before the string to convert to bytes array
    data = s.recv(1024)
print('Received', data.decode()) # repr is for returning string representation of an object