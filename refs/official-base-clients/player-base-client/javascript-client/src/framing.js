'use strict';

const MAX_BODY = 99999;

class FramedSocket {
  constructor(socket, onFrame) {
    this.socket = socket;
    this.onFrame = onFrame;
    this.buffer = Buffer.alloc(0);
    socket.on('data', (chunk) => this.receive(chunk));
  }

  receive(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 5) {
      const lengthText = this.buffer.subarray(0, 5).toString('utf8');
      const length = Number.parseInt(lengthText, 10);
      if (!Number.isInteger(length) || length < 0 || length > MAX_BODY) {
        throw new Error(`invalid frame length: ${lengthText}`);
      }
      if (this.buffer.length < 5 + length) {
        return;
      }
      const body = this.buffer.subarray(5, 5 + length).toString('utf8');
      this.buffer = this.buffer.subarray(5 + length);
      this.onFrame(JSON.parse(body), body);
    }
  }

  send(value) {
    const body = Buffer.from(JSON.stringify(value), 'utf8');
    if (body.length > MAX_BODY) {
      throw new Error(`message too large: ${body.length}`);
    }
    const prefix = Buffer.from(String(body.length).padStart(5, '0'), 'ascii');
    this.socket.write(Buffer.concat([prefix, body]));
  }
}

module.exports = { FramedSocket };
