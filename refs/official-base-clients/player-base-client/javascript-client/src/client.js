'use strict';

const net = require('net');

const { FramedSocket } = require('./framing');
const { heartbeatAction, readyMessage, registrationMessage } = require('./messages');

class BasicClient {
  constructor(config) {
    this.config = config;
    this.matchId = '';
    this.socket = null;
    this.framed = null;
  }

  start() {
    this.socket = net.createConnection(
      { host: this.config.host, port: this.config.port },
      () => this.onConnected()
    );
    this.framed = new FramedSocket(this.socket, (message, raw) => this.handleMessage(message, raw));
    this.socket.on('error', (error) => this.fail(error));
  }

  onConnected() {
    console.log(`connected to ${this.config.host}:${this.config.port} as player ${this.config.playerId}`);
    this.framed.send(registrationMessage(this.config));
  }

  handleMessage(message, raw) {
    if (message.msg_name === 'start') {
      this.handleStart(message.msg_data);
    } else if (message.msg_name === 'inquire') {
      this.handleInquire(message.msg_data);
    } else if (message.msg_name === 'over') {
      console.log('over received');
      this.socket.end();
    } else if (message.msg_name === 'error') {
      console.error(`error received: ${raw}`);
      process.exitCode = 1;
      this.socket.end();
    } else {
      console.log(`ignored msg_name=${message.msg_name}`);
    }
  }

  handleStart(data) {
    this.matchId = data.matchId;
    console.log(`start match=${this.matchId} round=${data.round}`);
    this.framed.send(readyMessage(this.matchId, data.round, this.config.playerId));
  }

  handleInquire(data) {
    console.log(`inquire round=${data.round} -> heartbeat`);
    this.framed.send(heartbeatAction(this.matchId, data.round, this.config.playerId));
  }

  fail(error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { BasicClient };
