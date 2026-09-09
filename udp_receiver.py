# receiver side

import socket

HOST = '127.0.0.1' # localhost
PORT = 50007

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s: #SOCK_DGRAM represents UDP
    s.bind((HOST, PORT)) # binding socket to host and port
    data, addr = s.recvfrom(1024) # receiving data from a socket and using sockfrom to get client address as well
    s.sendto(b'Received string is ' + data , addr)
print("Data received from ", addr[0], " is ", data.decode()) # decode can be used to decode byte strings to strings
