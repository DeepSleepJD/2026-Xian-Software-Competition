import type { ClientConfig } from './messages';

const USAGE =
  'Usage: node dist/src/basic_client.js [--host HOST] [--port PORT] [--player-id ID] [--player-name NAME] [--version VERSION]';

const DEFAULT_CONFIG: ClientConfig = {
  host: '127.0.0.1',
  port: 30000,
  playerId: 1005,
  playerName: 'BasicTs',
  version: '0.1'
};

export function parseArgs(argv: string[]): ClientConfig {
  const config = { ...DEFAULT_CONFIG };

  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    const readValue = () => {
      if (index + 1 >= argv.length) {
        throw new Error(`missing value for ${arg}`);
      }
      index += 1;
      return argv[index];
    };

    if (arg === '--host') {
      config.host = readValue();
    } else if (arg === '--port') {
      config.port = parseNumber(readValue(), arg);
    } else if (arg === '--player-id') {
      config.playerId = parseNumber(readValue(), arg);
    } else if (arg === '--player-name') {
      config.playerName = readValue();
    } else if (arg === '--version') {
      config.version = readValue();
    } else if (arg === '--help') {
      console.log(USAGE);
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }

  return config;
}

function parseNumber(value: string, optionName: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed)) {
    throw new Error(`invalid number for ${optionName}: ${value}`);
  }
  return parsed;
}
