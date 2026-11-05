const {test: base, expect} = require('@playwright/test');
const {RECOVERY_TEST_TIMEOUT,waitForRecoveredSync}=require('./sync-recovery.cjs');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');

// All accounts, permissions and business data belong to the disposable test DB.
// The fixture never injects production UI state or replaces an application API.
function fixture(command, value) {
  const output = execFileSync(process.env.ERFASSUNG_PYTHON,
    ['tests/browser/interface_fixture.py', command, value], {env: process.env, encoding: 'utf8'});
  return JSON.parse(output.trim().split('\n').at(-1));
}
const test = base.extend({
  accounts: async ({}, use) => {
    await use(fixture('create', `ui-${randomUUID().slice(0, 9)}`));
  },
});
async function login(page, accounts, kind = 'member') {
  await page.goto('/login');
  await page.locator('[name=username]').fill(accounts.actors[kind].username);
  await page.locator('[name=password]').fill(accounts.password);
  await Promise.all([page.waitForURL('**/dashboard'), page.locator('button[type=submit]').click()]);
}
async function mobile(page) {
  await page.goto('/mobile');
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, {once: true}));
    }
  });
}
function punch(page, action, root = 'body') {
  return page.locator(`${root} form`).filter({has: page.locator(`input[name=action][value=${action}]`)}).locator('button[type=submit]');
}
async function snapshot(page) { return (await (await page.request.get('/mobile/sync-data')).json()); }
async function capture(page, testInfo, name, fullPage = false) {
  if (process.env.ERFASSUNG_CAPTURE_UI === '1') {
    const screenshot = testInfo.outputPath(`${name}.png`);
    await page.screenshot({path: screenshot, fullPage, animations: 'disabled'});
    await testInfo.attach(name, {path: screenshot, contentType: 'image/png'});
  }
}
async function assertFits(page) {
  // Checking the inner panels prevents overflow:hidden on the document from
  // concealing a broken layout. Wide desktop tables may scroll in their own
  // dedicated container; the surrounding cards and dialogs still must fit.
  const result = await page.evaluate(() => {
    const visible = element => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const selectors = '.page,.mobile-dashboard,.mobile-panel,.card,.modal[aria-hidden="false"] .modal__dialog,.management-interface';
    const inner = [...document.querySelectorAll(selectors)].filter(visible).filter(element =>
      element.scrollWidth > element.clientWidth + 2 || element.getBoundingClientRect().right > innerWidth + 2
    ).map(element => ({tag: element.tagName, id: element.id, classes: element.className,
      width: element.clientWidth, content: element.scrollWidth, right: element.getBoundingClientRect().right}));
    return {route: location.pathname, document: document.documentElement.scrollWidth, viewport: innerWidth, inner};
  });
  expect(result.document, JSON.stringify(result)).toBeLessThanOrEqual(result.viewport + 1);
  expect(result.inner, JSON.stringify(result)).toEqual([]);
}
async function openTab(page, tab) {
  await page.locator(`[data-tab="${tab}"]`).filter({visible: true}).first().click();
  await expect(page.locator(`#mobile-panel-${tab}`)).toBeVisible();
}

test('web navigation preserves records, vacation, personal account and password access', async ({page, accounts}) => {
  await login(page, accounts);
  await expect(page.locator('a[href="/records"]').first()).toBeAttached();
  for (const route of ['/records', '/records/vacations', '/account', '/account/password']) {
    const response = await page.goto(route);
    expect(response.status(), route).toBe(200);
    await expect(page.locator('main')).toBeVisible();
  }
  await expect(page.locator('input[type=password]').first()).toBeVisible();
  await page.goto('/dashboard');
  await expect(punch(page, 'start_work')).toBeVisible();
  await page.locator('[data-disclose="manual-entry"]').click();
  await expect(page.locator('#manual-entry')).toHaveAttribute('open', '');
});

test('own QR is protected and administrative QR obeys group scope', async ({page, accounts, browser}) => {
  await login(page, accounts);
  await page.goto('/account');
  await expect(page.locator('#account-qr')).toBeVisible();
  const own = await page.request.get('/account/mobile-qr.png');
  expect(own.status()).toBe(200);
  expect(own.headers()['content-type']).toContain('image/png');
  expect(own.headers()['cache-control']).toContain('no-store');
  expect((await own.body()).subarray(0, 8)).toEqual(Buffer.from([137,80,78,71,13,10,26,10]));
  expect((await page.request.get(`/admin/users/${accounts.actors.outsider.id}/mobile-qr.png`)).status()).toBe(403);
  const guest = await browser.newContext({baseURL: `http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT || 8765}`});
  try {
    const response = await guest.request.get('/account/mobile-qr.png', {maxRedirects: 0});
    expect([302,303,401,403]).toContain(response.status());
  } finally { await guest.close(); }
  await page.goto('/logout');
  await login(page, accounts, 'lead');
  expect((await page.request.get(`/admin/users/${accounts.actors.member.id}/mobile-qr.png`)).status()).toBe(200);
  expect((await page.request.get(`/admin/users/${accounts.actors.outsider.id}/mobile-qr.png`)).status()).toBe(404);
});

test('saved day or week preference survives reload and stays personal across accounts', async ({page, accounts}) => {
  await login(page, accounts);
  await page.goto('/account');
  const form = page.locator('[data-account-preferences]');
  await form.locator('[name=overview_preference][value=week]').check();
  await Promise.all([
    page.waitForURL(url => url.pathname === '/account' && url.searchParams.get('msg') === 'Startansicht gespeichert', {waitUntil: 'load'}),
    form.locator('button[type=submit]').click(),
  ]);
  await page.reload();
  await expect(page.locator('[name=overview_preference][value=week]')).toBeChecked();
  expect(await (await page.request.get('/api/account/preferences')).json()).toMatchObject({
    user_id: accounts.actors.member.id, overview_preference: 'week',
  });
  await page.goto('/dashboard');
  await expect(page.locator('[data-overview-mode=week]')).toHaveAttribute('aria-current', 'page');
  await page.locator('[data-overview-mode=day]').click();
  expect((await (await page.request.get('/api/account/preferences')).json()).overview_preference).toBe('week');
  await mobile(page);
  await openTab(page, 'uebersicht');
  await expect(page.locator('[data-ov-mode=week]')).toHaveClass(/is-active/);
  await page.reload();
  await openTab(page, 'uebersicht');
  await expect(page.locator('[data-ov-mode=week]')).toHaveClass(/is-active/);
  // A different installed PWA belongs to the second account. Reusing the first
  // account's IndexedDB intentionally triggers the existing account-mismatch
  // protection, which is covered by sync.spec.cjs rather than this preference test.
  const other = await page.context().browser().newContext({
    baseURL: `http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT || 8765}`, viewport: page.viewportSize(),
  });
  try {
    const second = await other.newPage();
    await login(second, accounts, 'outsider');
    await second.goto('/account');
    await expect(second.locator('[name=overview_preference][value=day]')).toBeChecked();
    expect((await (await second.request.get('/api/account/preferences')).json()).user_id).toBe(accounts.actors.outsider.id);
    await mobile(second);
    await openTab(second, 'uebersicht');
    await expect(second.locator('[data-ov-mode=day]')).toHaveClass(/is-active/);
  } finally { await other.close(); }
});

test('web stamping creates a firm and persists start, pause, resume and finish', async ({page, accounts}, testInfo) => {
  await login(page, accounts);
  const company = `${accounts.actors.member.username}-Neue-Firma`;
  await page.locator('[data-open="order-modal"]').first().click();
  const dialog = page.locator('#order-modal');
  await expect(dialog).toHaveAttribute('aria-hidden', 'false');
  await dialog.locator('[name=new_company_name]').fill(company);
  await dialog.locator('[name=notes]').fill('Browserprüfung: Auftrag mit optionaler Firma');
  await Promise.all([page.waitForURL('**/dashboard**'), dialog.locator('button[type=submit]').click()]);
  await expect.poll(async () => (await snapshot(page)).active_entry?.company_name).toBe(company);
  const bookedDate = (await snapshot(page)).active_entry.work_date.split('-').reverse().join('.');
  await expect(page.locator('.punch-status')).toContainText(bookedDate);
  await expect(page.locator('.punch-status')).not.toContainText('01.01.1900');
  await capture(page, testInfo, 'web-dashboard-active');
  if (process.env.ERFASSUNG_CAPTURE_UI === '1') {
    if (await page.locator('html').getAttribute('data-theme') !== 'dark') {
      if (!await page.locator('[data-theme-toggle]').filter({visible: true}).count()) {
        await page.locator('[data-navigation-toggle]').click();
      }
      await page.locator('[data-theme-toggle]').filter({visible: true}).first().click();
      const navigation = page.locator('[data-navigation-toggle][aria-expanded=true]');
      if (await navigation.count()) await navigation.click();
    }
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await capture(page, testInfo, 'web-dashboard-dark', true);
  }
  await punch(page, 'start_break').click();
  await expect.poll(async () => (await snapshot(page)).active_entry?.break_started_at).toBeTruthy();
  await expect(page.locator('.punch-status')).toContainText(/Pause/);
  await expect(page.locator('.punch-status')).not.toContainText('01.01.1900');
  await punch(page, 'end_break').click();
  await expect.poll(async () => (await snapshot(page)).active_entry?.break_started_at).toBeFalsy();
  await punch(page, 'end_work').click();
  await expect.poll(async () => (await snapshot(page)).active_entry).toBeNull();
  await expect(punch(page, 'start_work')).toBeVisible();
  const saved = fixture('snapshot', accounts.actors.member.username);
  expect(saved.entries).toHaveLength(1);
  expect(saved.entries[0]).toMatchObject({company, status: 'approved'});
  expect(saved.entries[0].end).toBeTruthy();
});

test('PWA order and pause controls persist a real server booking and respect company permission', async ({page, accounts}, testInfo) => {
  await login(page, accounts);
  await mobile(page);
  const company = `${accounts.actors.member.username}-PWA-Firma`;
  await page.locator('[data-open="mobile-order-modal"]').first().click();
  const dialog = page.locator('#mobile-order-modal');
  await expect(dialog).toHaveAttribute('aria-hidden', 'false');
  await dialog.locator('[name=new_company_name]').fill(company);
  await dialog.locator('button[type=submit]').click();
  await expect.poll(async () => (await snapshot(page)).active_entry?.company_name).toBe(company);
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await capture(page, testInfo, 'pwa-running-order');
  await punch(page, 'start_break', '#mobile-panel-buchung').click();
  await expect.poll(async () => (await snapshot(page)).active_entry?.break_started_at).toBeTruthy();
  await punch(page, 'end_break', '#mobile-panel-buchung').click();
  await expect.poll(async () => (await snapshot(page)).active_entry?.break_started_at).toBeFalsy();
  await punch(page, 'end_work', '#mobile-panel-buchung').click();
  await expect.poll(async () => (await snapshot(page)).active_entry).toBeNull();
  expect(fixture('snapshot', accounts.actors.member.username).entries[0]).toMatchObject({company, status: 'approved'});
  const other = await page.context().browser().newContext({
    baseURL: `http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT || 8765}`, viewport: page.viewportSize(),
  });
  try {
    const restricted = await other.newPage();
    await login(restricted, accounts, 'outsider');
    await mobile(restricted);
    await restricted.locator('[data-open="mobile-order-modal"]').first().click();
    await expect(restricted.locator('#mobile-order-modal [name=new_company_name]')).not.toBeVisible();
    await expect(restricted.locator('#mobile-order-modal select[name=company_id]')).toBeVisible();
  } finally { await other.close(); }
});

test('all original PWA areas and settings remain reachable in the offline shell', async ({page, context, accounts}) => {
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await page.setViewportSize({width:390, height:844});
  await login(page, accounts);
  await mobile(page);
  await openTab(page, 'einstellungen');
  for (const selector of ['#mobile-clear-cache-btn', '[data-sync-export]', '[data-sync-import]']) {
    // Export/import hooks are deliberately preserved across the redesign.
    await expect(page.locator(selector)).toBeAttached();
  }
  await openTab(page, 'salden');
  await expect(page.locator('#mobile-panel-salden')).toContainText(/Soll|Urlaub|Saldo/);
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator('[data-sync-label]')).toHaveText('Offline');
  for (const tab of ['buchung', 'uebersicht', 'urlaub', 'einstellungen']) {
    await openTab(page, tab);
    await assertFits(page);
  }
  await openTab(page, 'salden');
  await assertFits(page);
  await openTab(page, 'buchung');
  await punch(page, 'start_work', '#mobile-panel-buchung').click();
  await expect.poll(() => page.evaluate(async () => {
    const store = new ErfassungSync.MobileStore();
    try { return (await store.pending()).length; } finally { store.close(); }
  })).toBe(1);
  await context.setOffline(false);
  await waitForRecoveredSync(page);
  await expect.poll(async () => (await snapshot(page)).active_entry).toBeTruthy();
});

test('administration keeps five groups, single-open navigation, keyboard dismissal and modal collapse', async ({page, accounts}, testInfo) => {
  await login(page, accounts, 'admin');
  await page.goto('/admin/users');
  await expect(page.locator('[data-adminnav] .adminnav__summary')).toHaveText([
    'Benutzer','Zeiterfassung','Sicherung','System','Einstellungen',
  ]);
  for (const key of ['time', 'backup', 'system']) {
    const summary = page.locator(`[data-adminnav] [data-group="${key}"] summary`);
    if (await page.evaluate(() => matchMedia('(hover: hover) and (min-width: 769px)').matches)) {
      await summary.hover();
      await summary.focus();
    } else {
      await summary.click();
    }
    await expect(page.locator('[data-adminnav] details[open]')).toHaveCount(1);
  }
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-adminnav] details[open]')).toHaveCount(0);
  await page.goto(`/admin/users/${accounts.actors.member.id}`);
  await expect(page.locator('[data-adminnav] details[open]')).toHaveCount(0);
  await expect(page.locator(`img[src^="/admin/users/${accounts.actors.member.id}/mobile-qr.png"]`)).toBeVisible();
  await capture(page, testInfo, 'admin-user-profile');
  await page.goto('/admin/system/database');
  const opener = page.locator('#db-configure');
  await opener.click();
  await expect(page.locator('#db-modal')).toHaveAttribute('aria-hidden', 'false');
  await expect(page.locator('[data-adminnav] details[open]')).toHaveCount(0);
  await assertFits(page);
  const modalControls = page.locator('#db-modal button:not([disabled]),#db-modal input:not([disabled]):not([type=hidden]),#db-modal select:not([disabled])').filter({visible: true});
  await modalControls.last().focus();
  await page.keyboard.press('Tab');
  await expect(modalControls.first()).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(modalControls.last()).toBeFocused();
  await page.locator('#db-modal [data-close]').filter({visible:true}).last().click();
  await expect(page.locator('#db-modal')).toHaveAttribute('aria-hidden', 'true');
  await expect(opener).toBeFocused();
});

test('PWA default-view setting is saved on the server and a transient switch does not overwrite it', async ({page, accounts}) => {
  await login(page, accounts);
  await mobile(page);
  await openTab(page, 'einstellungen');
  await page.locator('#mobile-setting-default-view').selectOption('week');
  await page.locator('#mobile-preference-form button[type=submit]').click();
  await expect(page.locator('#mobile-preference-feedback')).toContainText(/gespeichert/i);
  expect((await (await page.request.get('/api/account/preferences')).json()).overview_preference).toBe('week');
  await page.reload();
  await openTab(page, 'uebersicht');
  await expect(page.locator('[data-ov-mode=week]')).toHaveClass(/is-active/);
  await page.locator('[data-ov-mode=day]').click();
  expect((await (await page.request.get('/api/account/preferences')).json()).overview_preference).toBe('week');
});

test('administrative break correction preserves independent forms, reason and actual interval', async ({page, accounts}) => {
  await login(page, accounts, 'admin');
  await page.setViewportSize({width:390,height:844});
  const entry = accounts.break_entry;
  await page.goto(`/admin/time-entries/${entry.id}/edit`);
  await expect(page.locator('input[name=break_minutes]')).toHaveAttribute('readonly', '');
  const pause = page.locator(`#break-intervals form[action$="/breaks/${entry.break_id}"]`);
  await expect(pause).toBeVisible();
  await expect(pause.locator('[name=started_at]')).toHaveAttribute('step', '1');
  await expect(pause.locator('[name=ended_at]')).toHaveAttribute('step', '1');
  await expect(pause.locator('[name=change_reason]')).toHaveAttribute('required', '');
  expect(await pause.evaluate(form => form.parentElement.closest('form') === null)).toBe(true);
  await assertFits(page);
  const oldEnd = await pause.locator('[name=ended_at]').inputValue();
  const extended = new Date(`${oldEnd}${oldEnd.length === 16 ? ':00' : ''}Z`);
  extended.setUTCMinutes(extended.getUTCMinutes() + 15);
  await pause.locator('[name=ended_at]').fill(extended.toISOString().slice(0,19));
  await pause.locator('[name=change_reason]').fill('Pause anhand des tatsächlichen Endes berichtigt');
  await pause.locator('button[type=submit]').click();
  await expect(page.locator('input[name=break_minutes]')).toHaveValue('45');
  expect(await page.locator('#break-intervals [name=ended_at]').inputValue()).toMatch(/:23$/);
  const saved = fixture('snapshot', accounts.actors.lead.username);
  expect(saved.entries.find(row => row.id === entry.id)).toMatchObject({break_minutes:45,status:'approved'});
});

test('long names and original forms fit phone, tablet and landscape without hidden inner overflow', async ({page, accounts}) => {
  test.setTimeout(120000);
  await login(page, accounts, 'admin');
  for (const viewport of [{width:320,height:720},{width:390,height:844},{width:844,height:390}]) {
    await page.setViewportSize(viewport);
    for (const route of ['/dashboard', '/account', '/records', '/records/vacations', '/admin/users', `/admin/users/${accounts.actors.member.id}`, '/admin/reports/time', '/admin/approvals']) {
      const response = await page.goto(route);
      expect(response.status(), route).toBe(200);
      await assertFits(page);
    }
    await mobile(page);
    for (const tab of ['buchung', 'uebersicht', 'urlaub', 'einstellungen']) {
      await openTab(page, tab);
      await assertFits(page);
    }
    await openTab(page, 'buchung');
    await page.locator('[data-open="mobile-order-modal"]').first().click();
    await expect(page.locator('#mobile-order-modal')).toHaveAttribute('aria-hidden', 'false');
    await assertFits(page);
    await page.locator('#mobile-order-modal button[data-close]').first().click();
  }
});
