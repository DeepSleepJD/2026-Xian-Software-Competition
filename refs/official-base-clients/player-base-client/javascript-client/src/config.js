'use strict';

const USAGE = 'Usage: node src/basic_client.js [--host HOST] [--port PORT] [--player-id ID] [--player-name NAME] [--version VERSION]';

function parseArgs(argv) {
  const config = {
    host: '127.0.0.1',
    port: 30000,
    playerId: 1005,
    playerName: 'BasicJs',
    version: '0.1'
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      if (i + 1 >= argv.length) {
        throw new Error(`missing value for ${arg}`);
      }
      i += 1;
      return argv[i];
    };

    if (arg === '--host') {
      config.host = next();
    } else if (arg === '--port') {
      config.port = Number.parseInt(next(), 10);
    } else if (arg === '--player-id') {
      config.playerId = Number.parseInt(next(), 10);
    } else if (arg === '--player-name') {
      config.playerName = next();
    } else if (arg === '--version') {
      config.version = next();
    } else if (arg === '--help') {
      console.log(USAGE);
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return config;
}

module.exports = { parseArgs };
