const { defineConfig, devices } = require('@playwright/test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
process.env.ERFASSUNG_E2E_ROOT ||= fs.mkdtempSync(path.join(os.tmpdir(), 'erfassung-pwa-'));
process.env.ERFASSUNG_PYTHON ||= fs.existsSync('.venv/bin/python') ? path.resolve('.venv/bin/python') : 'python';
module.exports = defineConfig({
  testDir: './tests/browser', testMatch: '**/*.spec.cjs', fullyParallel: false, workers: 1,
  timeout: 45000, expect: { timeout: 12000 }, retries: 0,
  reporter: process.env.CI ? [['line'], ['github'], ['junit', { outputFile: 'test-results/browser.xml' }]] : [['list']],
  use: { baseURL: 'http://127.0.0.1:8765', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name:'chromium',use:{...devices['Desktop Chrome'],launchOptions:process.env.ERFASSUNG_CHROMIUM_PATH?{executablePath:process.env.ERFASSUNG_CHROMIUM_PATH}:{} }},
    { name:'webkit',use:{...devices['iPhone 13'],defaultBrowserType:'webkit'} },
  ],
  webServer: { command: `${process.env.ERFASSUNG_PYTHON} tests/browser/serve.py`, url:'http://127.0.0.1:8765/health',reuseExistingServer:false,timeout:45000 },
});
