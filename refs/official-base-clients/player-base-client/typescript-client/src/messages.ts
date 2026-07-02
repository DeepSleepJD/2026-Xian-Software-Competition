export interface ClientConfig {
  host: string;
  port: number;
  playerId: number;
  playerName: string;
  version: string;
}

export interface ClientMessage {
  msg_name: string;
  msg_data: Record<string, unknown>;
}

export function registrationMessage(config: ClientConfig): ClientMessage {
  return {
    msg_name: 'registration',
    msg_data: {
      playerId: config.playerId,
      playerName: config.playerName,
      version: config.version
    }
  };
}

export function readyMessage(matchId: string, round: number, playerId: number): ClientMessage {
  return {
    msg_name: 'ready',
    msg_data: {
      matchId,
      round,
      playerId
    }
  };
}

export function heartbeatAction(matchId: string, round: number, playerId: number): ClientMessage {
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

export function moveAction(
  matchId: string,
  round: number,
  playerId: number,
  targetNodeId: string
): ClientMessage {
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
