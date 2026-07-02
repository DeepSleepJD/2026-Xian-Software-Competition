import { BasicClient } from './client';
import { parseArgs } from './config';

function main(): void {
  new BasicClient(parseArgs(process.argv)).start();
}

main();
