import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';

import { BasicClient } from '../src/client';
import { parseArgs } from '../src/config';
import { FramedSocket } from '../src/framing';
import { heartbeatAction, moveAction } from '../src/messages';

class FakeSocket extends EventEmitter {
  public written = Buffer.alloc(0);
  public ended = false;

  write(chunk: Buffer) {
    this.written = Buffer.concat([this.written, chunk]);
  }

  end() {
    this.ended = true;
  }
}

test('FramedSocket sends a length-prefixed JSON frame', () => {
  let written = Buffer.alloc(0);
  const socket = {
    on() {},
    write(chunk: Buffer) {
      written = Buffer.concat([written, chunk]);
    }
  };
  const framed = new FramedSocket(socket, () => {});

  framed.send({ msg_name: 'ping' });

  assert.equal(written.toString('utf8'), '00019{"msg_name":"ping"}');
});

test('FramedSocket parses a split frame', () => {
  const frames: Array<{ value: unknown; raw: string }> = [];
  const socket = { on() {}, write() {} };
  const framed = new FramedSocket(socket, (value, raw) => frames.push({ value, raw }));

  framed.receive(Buffer.from('00019{"msg_name"', 'utf8'));
  framed.receive(Buffer.from(':"pong"}', 'utf8'));

  assert.deepEqual(frames, [
    { value: { msg_name: 'pong' }, raw: '{"msg_name":"pong"}' }
  ]);
});

test('heartbeatAction keeps actions empty', () => {
  assert.deepEqual(heartbeatAction('match-1', 7, 1005), {
    msg_name: 'action',
    msg_data: {
      matchId: 'match-1',
      round: 7,
      playerId: 1005,
      actions: []
    }
  });
});

test('moveAction uses targetNodeId', () => {
  assert.deepEqual(moveAction('match-1', 7, 1005, 'S10'), {
    msg_name: 'action',
    msg_data: {
      matchId: 'match-1',
      round: 7,
      playerId: 1005,
      actions: [
        {
          action: 'MOVE',
          targetNodeId: 'S10'
        }
      ]
    }
  });
});

test('parseArgs keeps defaults and accepts overrides', () => {
  assert.deepEqual(
    parseArgs([
      'node',
      'basic_client.js',
      '--host',
      'localhost',
      '--port',
      '30001',
      '--player-id',
      '42',
      '--player-name',
      'TypeScriptPlayer',
      '--version',
      '0.2'
    ]),
    {
      host: 'localhost',
      port: 30001,
      playerId: 42,
      playerName: 'TypeScriptPlayer',
      version: '0.2'
    }
  );
});

test('BasicClient writes registration ready and heartbeat frames to the socket', () => {
  const socket = new FakeSocket();
  const client = new BasicClient(
    {
      host: '127.0.0.1',
      port: 30000,
      playerId: 1005,
      playerName: 'BasicTs',
      version: '0.1'
    },
    () => socket,
    { error() {}, log() {} }
  );

  client.start();
  socket.emit('connect');
  socket.emit('data', frame({ msg_name: 'start', msg_data: { matchId: 'match-1', round: 1 } }));
  socket.emit('data', frame({ msg_name: 'inquire', msg_data: { round: 2 } }));

  assert.deepEqual(readFrames(socket.written), [
    {
      msg_name: 'registration',
      msg_data: {
        playerId: 1005,
        playerName: 'BasicTs',
        version: '0.1'
      }
    },
    {
      msg_name: 'ready',
      msg_data: {
        matchId: 'match-1',
        round: 1,
        playerId: 1005
      }
    },
    {
      msg_name: 'action',
      msg_data: {
        matchId: 'match-1',
        round: 2,
        playerId: 1005,
        actions: []
      }
    }
  ]);
});

function frame(value: unknown): Buffer {
  const body = Buffer.from(JSON.stringify(value), 'utf8');
  const prefix = Buffer.from(String(body.length).padStart(5, '0'), 'ascii');
  return Buffer.concat([prefix, body]);
}

function readFrames(buffer: Buffer): unknown[] {
  const frames: unknown[] = [];
  let offset = 0;
  while (offset < buffer.length) {
    const bodyLength = Number.parseInt(buffer.subarray(offset, offset + 5).toString('ascii'), 10);
    offset += 5;
    frames.push(JSON.parse(buffer.subarray(offset, offset + bodyLength).toString('utf8')));
    offset += bodyLength;
  }
  return frames;
}
