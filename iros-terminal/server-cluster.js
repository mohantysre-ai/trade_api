const cluster = require('node:cluster');
const os = require('node:os');

const workers = Math.max(1, Number(process.env.FRONTEND_WORKERS || Math.min(2, os.availableParallelism())));
if (cluster.isPrimary && workers > 1) {
  for (let index = 0; index < workers; index += 1) cluster.fork();
  cluster.on('exit', (worker) => {
    if (!worker.exitedAfterDisconnect) cluster.fork();
  });
} else {
  require('./server.js');
}
