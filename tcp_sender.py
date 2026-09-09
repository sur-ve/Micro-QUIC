# echo server program

import socket

HOST = '' # name available to all interfaces
PORT = 50007 # non-privileged port
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: # we use with..as to handle automatic garbage collection
    s.bind((HOST, PORT)) # binds socket s to port 50007
    s.listen(1) # listens for 1 connection and then rejects
    conn, addr = s.accept() # the accept method returns a socket and we use this socket for receiving and sending data as socket s is exclusively used for waiting for and accepting new connection requests
    with conn: 
        print('Connected by ', addr)
        while True:
            data = conn.recv(1024) # read 1024 vytes of data
            if not data : break
            conn.sendall(data) # send back all data to sending client
