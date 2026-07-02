const MAX_BODY_LENGTH = 99999;
const PREFIX_LENGTH = 5;

export interface SocketLike {
  on(eventName: string, listener: (...args: unknown[]) => void): void;
  write(chunk: Buffer): void;
}

export type FrameHandler = (value: unknown, raw: string) => void;

export class FramedSocket {
  private buffer = Buffer.alloc(0);

  public constructor(
    private readonly socket: SocketLike,
    private readonly onFrame: FrameHandler
  ) {
    this.socket.on('data', (chunk) => this.receive(toBuffer(chunk)));
  }

  public receive(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.hasCompletePrefix()) {
      const bodyLength = this.readBodyLength();
      if (!this.hasCompleteBody(bodyLength)) {
        return;
      }
      this.emitFrame(bodyLength);
    }
  }

  public send(value: unknown): void {
    const body = Buffer.from(JSON.stringify(value), 'utf8');
    if (body.length > MAX_BODY_LENGTH) {
      throw new Error(`message too large: ${body.length}`);
    }
    this.socket.write(Buffer.concat([lengthPrefix(body.length), body]));
  }

  private hasCompletePrefix(): boolean {
    return this.buffer.length >= PREFIX_LENGTH;
  }

  private readBodyLength(): number {
    const lengthText = this.buffer.subarray(0, PREFIX_LENGTH).toString('ascii');
    const bodyLength = Number.parseInt(lengthText, 10);
    if (!Number.isInteger(bodyLength) || bodyLength < 0 || bodyLength > MAX_BODY_LENGTH) {
      throw new Error(`invalid frame length: ${lengthText}`);
    }
    return bodyLength;
  }

  private hasCompleteBody(bodyLength: number): boolean {
    return this.buffer.length >= PREFIX_LENGTH + bodyLength;
  }

  private emitFrame(bodyLength: number): void {
    const body = this.buffer.subarray(PREFIX_LENGTH, PREFIX_LENGTH + bodyLength).toString('utf8');
    this.buffer = this.buffer.subarray(PREFIX_LENGTH + bodyLength);
    this.onFrame(JSON.parse(body), body);
  }
}

function lengthPrefix(bodyLength: number): Buffer {
  return Buffer.from(String(bodyLength).padStart(PREFIX_LENGTH, '0'), 'ascii');
}

function toBuffer(value: unknown): Buffer {
  if (!Buffer.isBuffer(value)) {
    throw new Error('socket data must be a Buffer');
  }
  return value;
}
