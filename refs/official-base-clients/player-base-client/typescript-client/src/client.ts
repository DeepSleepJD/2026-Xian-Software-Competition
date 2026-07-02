import net from 'node:net';

import { FramedSocket, type SocketLike } from './framing';
import {
  heartbeatAction,
  readyMessage,
  registrationMessage,
  type ClientConfig
} from './messages';

interface ClientSocket extends SocketLike {
  end(): void;
}

type Connect = (config: ClientConfig) => ClientSocket;

interface Logger {
  error(message: string): void;
  log(message: string): void;
}

export class BasicClient {
  private framed?: FramedSocket;
  private matchId = '';
  private socket?: ClientSocket;

  public constructor(
    private readonly config: ClientConfig,
    private readonly connect: Connect = createSocket,
    private readonly logger: Logger = console
  ) {}

  public start(): void {
    this.socket = this.connect(this.config);
    this.framed = new FramedSocket(this.socket, (message, raw) => this.handleMessage(message, raw));
    this.socket.on('connect', () => this.onConnected());
    this.socket.on('error', (error) => this.fail(toError(error)));
  }

  private onConnected(): void {
    this.logger.log(`connected to ${this.config.host}:${this.config.port} as player ${this.config.playerId}`);
    this.send(registrationMessage(this.config));
  }

  private handleMessage(message: unknown, raw: string): void {
    const msgName = stringField(message, 'msg_name');
    const msgData = objectField(message, 'msg_data');

    if (msgName === 'start') {
      this.handleStart(msgData);
    } else if (msgName === 'inquire') {
      this.handleInquire(msgData);
    } else if (msgName === 'over') {
      this.handleOver();
    } else if (msgName === 'error') {
      this.handleError(raw);
    } else {
      this.logger.log(`ignored msg_name=${msgName}`);
    }
  }

  private handleStart(data: Record<string, unknown>): void {
    this.matchId = requiredString(data, 'matchId');
    const round = requiredNumber(data, 'round');
    this.logger.log(`start match=${this.matchId} round=${round}`);
    this.send(readyMessage(this.matchId, round, this.config.playerId));
  }

  private handleInquire(data: Record<string, unknown>): void {
    const round = requiredNumber(data, 'round');
    this.logger.log(`inquire round=${round} -> heartbeat`);
    this.send(heartbeatAction(this.matchId, round, this.config.playerId));
  }

  private handleOver(): void {
    this.logger.log('over received');
    this.socket?.end();
  }

  private handleError(raw: string): void {
    this.logger.error(`error received: ${raw}`);
    process.exitCode = 1;
    this.socket?.end();
  }

  private fail(error: Error): void {
    this.logger.error(error.message);
    process.exitCode = 1;
  }

  private send(value: unknown): void {
    if (!this.framed) {
      throw new Error('client is not connected');
    }
    this.framed.send(value);
  }
}

function createSocket(config: ClientConfig): ClientSocket {
  return net.createConnection({ host: config.host, port: config.port });
}

function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}

function objectField(value: unknown, fieldName: string): Record<string, unknown> {
  const record = asRecord(value);
  return asRecord(record[fieldName]);
}

function stringField(value: unknown, fieldName: string): string {
  const fieldValue = asRecord(value)[fieldName];
  return typeof fieldValue === 'string' ? fieldValue : '';
}

function requiredString(record: Record<string, unknown>, fieldName: string): string {
  const value = record[fieldName];
  if (typeof value !== 'string') {
    throw new Error(`missing string field: ${fieldName}`);
  }
  return value;
}

function requiredNumber(record: Record<string, unknown>, fieldName: string): number {
  const value = record[fieldName];
  if (typeof value !== 'number') {
    throw new Error(`missing number field: ${fieldName}`);
  }
  return value;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}
