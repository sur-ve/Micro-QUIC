# Micro-QUIC
---

Micro-QUIC adds a header over User Datagram Protocol(UDP), that helps performs selective retransmission of critical data packets, ensuring faster data transmission speeds than Transmission Control Protocol(TCP) in lossy environments, at the cost of non-critical packets being lost.

## How it works
### TCP functioning
* TCP performs multiple data transmissions for a single data packet transfer from client to server.
* It first establishes the connection using **three-way handshaking**, involving SYN, SYN-ACK, ACK data packet transmission.
* Then during the data transmission from client to server or vice-versa, the data is segmented and sequenced. These sequenced packets are then transmitted to the server and an acknowledgment(ACK) packet is sent back to the client once the packet is received. The data packets are then sequenced on the receiver side and processed.
* Connection termination also takes 3-4 data transmissions between the two nodes(FIN, FIN-ACK, FIN).

### UDP functioning
* UDP does not establish the connection using any sort of handshaking. It just shoots the packet to the address provided.
* No acknowledgement is received upon data packet reception by the server.
* So for the transfer of a singular data packet, it takes UDP only one data packet transmission.

* We can identify that TCP introduces a huge overhead for every packet transmitted using it. On comparing with UDP, for the tranmsission of a single data packet, TCP takes 6 - 7 more data packet transmissions
* However on the other hand, since there is no connection establishment and acknowledgement, UDP may cause packet losses in lossy environments leading to critical data packets being lost, with no means of retrieval or retransmission.
* Micro-QUIC addresses this exact problem by introducing a new header over UDP for allowing selective retransmission of certain packets.
  
## The new UDP header
* The usual UDP header consists of four 16-bit blocks - source port, destination port, length and checksum.
* When data is transmitted using UDP, there is no sequencing, acknowledgement or error checking. These functionalities must be added if we want to perform selective retransmission.
* So we add these functionalities - sequence number, acknowledgement number, CRC and a flags byte to classify whether a packet is critical or not and also to classify whether it is an acknowledgement or not.

