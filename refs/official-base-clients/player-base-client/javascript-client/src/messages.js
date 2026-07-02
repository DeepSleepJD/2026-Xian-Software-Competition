'use strict';

function registrationMessage(config) {
  return {
    msg_name: 'registration',
    msg_data: {
      playerId: config.playerId,
      playerName: config.playerName,
      version: config.version
    }
  };
}

function readyMessage(matchId, round, playerId) {
  return {
    msg_name: 'ready',
    msg_data: {
      matchId,
      round,
      playerId
    }
  };
}

function heartbeatAction(matchId, round, playerId) {
  return {
    msg_name: 'action',
    msg_data: {
      matchId,
      round,
      playerId,
      actions: []
    }
  };
}

function moveAction(matchId, round, playerId, targetNodeId) {
  return {
    msg_name: 'action',
    msg_data: {
      matchId,
      round,
      playerId,
      actions: [
        {
          action: 'MOVE',
          targetNodeId
        }
      ]
    }
  };
}

module.exports = { heartbeatAction, moveAction, readyMessage, registrationMessage };
