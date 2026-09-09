# sender side

import socket

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.sendto(b'helloww', ('127.0.0.1', 50007)) # sends to the receiver using the receiver address
    # the sender is assigned an ephemeral local port, so replies have somewhere to go back to, though we never use bind
    data, address = s.recvfrom(1024)
print("Echo data from ", address[0], ", is: ", data.decode())

# sendto() returning successfully does not mean the packet arrived, it just means the OS handed it to network stack
# if receiver isnt running yet, sendto wont error, it just fires the packet into the void, This must be dealt with using feedback ACKs
# recvfrom() blocks forever by default if nothing arrives. We need to set a timeout so that retransmit on timeout logic triggers
# we use recvfrom to receive echo from receiver as we need to verify who is sending it. In case of UDP, there may be multiple sockets sending data on the same port, so we need to verify who is sending the data before processing