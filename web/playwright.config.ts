import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig } from '@playwright/test'

const data = mkdtempSync(join(tmpdir(), 'lifeos-browser-')).replaceAll('\\', '/')

export default defineConfig({
  testDir: './e2e',
  use: { baseURL: 'http://127.0.0.1:15173', channel: process.env.LIFEOS_BROWSER_CHANNEL },
  webServer: [
    {
      command: 'uv run --locked uvicorn personal_ai_life_os.main:app --host 127.0.0.1 --port 18000',
      cwd: '..',
      url: 'http://127.0.0.1:18000/api/v1/ready',
      env: {
        APP_ENV: 'test',
        DATABASE_URL: 'sqlite+pysqlite:///' + data + '/e2e.sqlite3',
        DATA_DIR: data,
        AUTO_CREATE_SCHEMA: 'true',
        REGISTRATION_MODE: 'open',
        REGISTRATION_RATE_LIMIT: '100',
        OBJECT_STORE_BACKEND: 'local',
        MODEL_PROVIDER: 'openai',
        OPENAI_API_KEY: 'synthetic-e2e-key',
        OPENAI_BASE_URL: 'https://models.example.test/v1',
        OPENAI_MODEL: 'synthetic-default',
        MODEL_PRIVACY_URL: 'https://models.example.test/privacy',
        MODEL_INPUT_COST_PER_MILLION_USD: '1',
        MODEL_OUTPUT_COST_PER_MILLION_USD: '1',
        MODEL_PROVIDERS: JSON.stringify({
          research: {
            base_url: 'https://models.example.test/v1',
            api_key: 'synthetic-e2e-named-key',
            model: 'model-b',
            models: ['model-b', 'model-b-mini'],
            input_cost_per_million_usd: '2',
            output_cost_per_million_usd: '3',
            privacy_url: 'https://models.example.test/privacy',
            retention: 'Synthetic browser evaluation provider retention policy.',
            disclosure_version: 'research-v1',
          },
        }),
        PROCESSING_MODE: 'inline',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 15173 --strictPort',
      url: 'http://127.0.0.1:15173',
      env: { LIFEOS_API_ORIGIN: 'http://127.0.0.1:18000' },
    },
  ],
})
