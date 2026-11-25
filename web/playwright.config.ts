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
        OBJECT_STORE_BACKEND: 'local',
        MODEL_PROVIDER: 'none',
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
