import type { Env as WorkerEnv } from '../worker/core';

declare global {
  namespace Cloudflare {
    interface Env extends WorkerEnv {
      TEST_MIGRATIONS: Array<{ name: string; queries: string[] }>;
    }
  }
}
