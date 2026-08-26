# Micro-QUIC - Selective Retransmission over UDP
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

* We can identify that TCP introduces a huge overhead for every packet transmitted using it. On comparing with UDP, for the tranmsission of a single data packet, TCP takes 8 more data packet transmissions
* However on the other hand, since there is no connection establishment and acknowledgement, UDP may cause packet losses in lossy environments leading to critical data packets being lost, with no means of retrieval or retransmission.
* Micro-QUIC addresses this exact problem by introducing a new header over UDP for allowing selective retransmission of certain packets.
  
## The new UDP header
* The usual UDP header consists of four 16-bit blocks - source port, destination port, length and checksum.
* When data is transmitted using UDP, there is no sequencing, acknowledgement or error checking. These functionalities must be added if we want to perform selective retransmission.
* So we add these functionalities:
  1. Sequence Number = 4 Bytes
  2. Acknowledgment Number = 4 Bytes
  3. Type / Flags = 1 Byte
  4. CRC-32 = 4 Bytes
* The flag bytes consists of the following bits
  * Bit 0 = ACK flag
  * Bit 1 = Critical flag
  * Bit 2 = More fragments flag
  * Bits 3-7 = Reserved
  A flag byte was chosen over an enum so that future functionalities can be easily integrated.

## Micro-QUIC functioning
  * When a data packet is labeled non-critical, it's loss does not trigger retransmission, thereby cutting the overhead.
  * When a packet is labeled critical, the server sends back an acknowledgement ACK packet to the client. This acknowledgment is not cumulative as in TCP but is per-packet acknowledgement.
  * However if this packet is lost, the ACK is not sent back to the client and the client retransmits the packet based on a fixed timer (ARQ).
