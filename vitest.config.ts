import { defineConfig } from 'vitest/config';
import { cloudflareTest, readD1Migrations } from '@cloudflare/vitest-plugin';

export default defineConfig(async () => {
  const migrations = await readD1Migrations('./migrations');
  return {
    plugins: [cloudflareTest({
      main: './worker/index.ts',
      remoteBindings: false,
      miniflare: {
        compatibilityDate: '2026-10-20',
        compatibilityFlags: ['nodejs_compat'],
        d1Databases: ['DB'],
        kvNamespaces: ['MEDIA'],
        bindings: {
          APP_SECRET: 'test-only-secret-at-least-thirty-two-characters',
          APP_URL: 'http://localhost:8787',
          TEST_MIGRATIONS: migrations,
          AI: {},
        },
        serviceBindings: {
          ASSETS: async () => new Response('Test static asset', { status: 200 }),
          BROWSER: async () => new Response('Browser Run mocked in local tests', { status: 503 }),
        },
      },
    })],
    test: {
      include: ['tests/**/*.test.ts'],
      setupFiles: ['./tests/setup.ts'],
      testTimeout: 15000,
      hookTimeout: 15000,
      fileParallelism: false,
    },
  };
});
