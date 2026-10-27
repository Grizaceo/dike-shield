import { createEnginesServer, createHmem } from "./server.ts";

const HOST = process.env.ENGINES_HOST ?? "127.0.0.1";
const PORT = Number(process.env.ENGINES_PORT ?? "8790");

const server = createEnginesServer(createHmem());
server.listen(PORT, HOST, () => {
  process.stdout.write(`engines sidecar http://${HOST}:${PORT} hmem=true markovian=true\n`);
});
