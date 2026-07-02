'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { FramedSocket } = require('../src/framing');
const { heartbeatAction, moveAction } = require('../src/messages');

test('FramedSocket sends a length-prefixed JSON frame', () => {
  let written = Buffer.alloc(0);
  const socket = {
    on() {},
    write(chunk) {
      written = Buffer.concat([written, chunk]);
    }
  };
  const framed = new FramedSocket(socket, () => {});

  framed.send({ msg_name: 'ping' });

  assert.equal(written.toString('utf8'), '00019{"msg_name":"ping"}');
});

test('FramedSocket parses a split frame', () => {
  const frames = [];
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
