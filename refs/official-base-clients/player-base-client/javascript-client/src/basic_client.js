'use strict';

const { BasicClient } = require('./client');
const { parseArgs } = require('./config');

function main() {
  new BasicClient(parseArgs(process.argv)).start();
}

main();
