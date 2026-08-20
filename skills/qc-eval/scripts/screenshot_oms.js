#!/usr/bin/env node
// OMS 字段统一题截图脚本：
//   01_order_list     — 订单列表，验证统一字段在普通列表可读
//   02_order_detail   — 打开订单详情抽屉
//   03_field_source   — 切到字段来源/调试信息区域
//
// 用法：node screenshot_oms.js <TASK_ID> [--only COL] [--base-port 5200]

const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, '..', '..', '..');

function parseArgs(argv) {
  const out = { id: null, only: null, basePort: 5200, keep: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--only') out.only = argv[++i];
    else if (a === '--base-port') out.basePort = parseInt(argv[++i], 10);
    else if (a === '--keep-existing') out.keep = true;
    else out.id = a;
  }
  if (!out.id) {
    console.error('usage: screenshot_oms.js <TASK_ID> [--only COL] [--base-port 5200] [--keep-existing]');
    process.exit(2);
  }
  return out;
}

function sanitize(s) {
  return s.replace(/[^A-Za-z0-9._-]+/g, '_');
}

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;]*m/g, '');
}

async function waitForViteUrl(child, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let buf = '';
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = stripAnsi(buf).match(/Local:\s*(https?:\/\/[^\s]+?\/)/);
      if (m) {
        cleanup();
        resolve(m[1]);
      }
    };
    const onErr = (chunk) => { buf += chunk.toString(); };
    const cleanup = () => {
      clearTimeout(t);
      child.stdout.off('data', onData);
      child.stderr.off('data', onErr);
      child.off('exit', onExit);
    };
    const onExit = (code) => {
      cleanup();
      reject(new Error(`vite exited with code ${code}. last:\n${buf.slice(-1200)}`));
    };
    const t = setTimeout(() => {
      cleanup();
      reject(new Error(`vite did not print Local: URL within ${timeoutMs}ms. last:\n${buf.slice(-1200)}`));
    }, timeoutMs);
    child.stdout.on('data', onData);
    child.stderr.on('data', onErr);
    child.on('exit', onExit);
  });
}

function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
  } else {
    try { process.kill(-pid); } catch {}
    try { process.kill(pid); } catch {}
  }
}

function ensureViteBin(entryDir) {
  const viteBin = process.platform === 'win32'
    ? path.join(entryDir, 'node_modules', '.bin', 'vite.CMD')
    : path.join(entryDir, 'node_modules', '.bin', 'vite');
  if (fs.existsSync(viteBin)) return viteBin;
  console.log(`     [deps] npm install in ${entryDir}`);
  const r = spawnSync('npm install --no-audit --no-fund', {
    cwd: entryDir,
    shell: true,
    stdio: 'inherit',
    env: { ...process.env, CI: 'true' },
  });
  if (r.status !== 0) throw new Error(`npm install failed in ${entryDir}`);
  if (!fs.existsSync(viteBin)) throw new Error(`vite bin missing after npm install in ${entryDir}`);
  return viteBin;
}

async function startDev(entryDir, port) {
  const viteBin = ensureViteBin(entryDir);
  const cmd = `"${viteBin}" --host 127.0.0.1 --port ${port} --strictPort`;
  console.log(`     starting ${cmd}`);
  const child = spawn(cmd, { cwd: entryDir, shell: true, windowsHide: true });
  const url = await waitForViteUrl(child).catch((e) => {
    killTree(child.pid);
    throw e;
  });
  return { child, url: url.replace(/\/$/, '') };
}

function sampleOrders() {
  const now = new Date().toISOString();
  const fieldSources = {
    platform_order_id: {
      unified_field: 'platform_order_id',
      platform: 'taobao',
      source_api: 'taobao.trades.sold.get',
      json_path: '$.tid',
      source_field: 'tid',
      source_layer: 'list_api',
      unit_source: null,
      transform_rule: 'string_passthrough',
      confidence: 'confirmed_by_official_doc',
      evidence_source: 'official_doc',
      why_this_field: '平台主订单号用于跨系统对账',
      why_not_others: '子订单号只用于明细行',
      mapping_schema_version: '2026-06-15-v1',
      needs_fill: false,
      missing_reason: null,
    },
    receiver_mobile_masked: {
      unified_field: 'receiver_mobile_masked',
      platform: 'taobao',
      source_api: 'taobao.trade.fullinfo.get',
      json_path: '$.receiver_mobile',
      source_field: 'receiver_mobile',
      source_layer: 'privacy_decrypt',
      unit_source: null,
      transform_rule: 'mask_after_decrypt',
      confidence: 'need_auth_confirmation',
      evidence_source: 'platform_backend_screenshot',
      why_this_field: '收货人手机号需要隐私解密后才能补齐',
      why_not_others: 'buyer_nick 不能代表收货人联系方式',
      mapping_schema_version: '2026-06-15-v1',
      needs_fill: true,
      missing_reason: '需要真实店铺授权和隐私解密接口',
    },
  };
  const base = [
    {
      id: 'ord_taobao_001',
      platform: 'taobao',
      shop_id: 'tb_001',
      shop_name: '淘天旗舰店',
      platform_shop_id: 'tb_shop_001',
      platform_order_id: 'TB202607080001',
      parent_order_id: null,
      order_type: 'normal',
      status: 'pending_shipment',
      order_trade_status: 'pending_shipment',
      order_display_status: 'pending_shipment',
      platform_status: 'WAIT_SELLER_SEND_GOODS',
      shipment_status: 'not_shipped',
      refund_status: 'none',
      after_sale_status: 'none',
      buyer_name: '张三',
      buyer_phone: '138****1234',
      buyer_address: '浙江省杭州市余杭区****',
      buyer_display_name: '张三',
      buyer_platform_id: 'tb_buyer_001',
      buyer_message: '尽快发货',
      buyer_memo: '重点客户',
      buyer_tags_json: JSON.stringify(['高复购']),
      receiver_name_masked: '张*',
      receiver_mobile_masked: '138****1234',
      receiver_region: '浙江省杭州市余杭区',
      receiver_address_masked: '未来科技城****',
      receiver_privacy_status: 'masked',
      actual_payment: 129.9,
      total_amount: 159.9,
      freight: 0,
      discount: 30,
      actual_pay_amount: 12990,
      order_total_amount: 15990,
      freight_amount: 0,
      discount_amount: 3000,
      actual_pay_amount_fen: 12990,
      order_total_amount_fen: 15990,
      freight_amount_fen: 0,
      discount_amount_fen: 3000,
      amount_unit_source: 'yuan_string_to_fen_int',
      paid_at: now,
      shipped_at: null,
      accepted_at: null,
      signed_at: null,
      completed_at: null,
      promised_ship_at: now,
      created_at: now,
      updated_at: now,
      synced_at: now,
      local_flag_color: 2,
      local_seller_remark: '字段统一验证样例',
      platform_flag_color: 1,
      platform_seller_remark: '平台备注',
      platform_tags_json: JSON.stringify({ privacy: 'masked' }),
      raw_payload_ref: 'raw://taobao/TB202607080001',
      mapping_schema_version: '2026-06-15-v1',
      field_source_json: JSON.stringify(fieldSources),
      field_sources: Object.values(fieldSources),
      items: [
        {
          id: 'item_1',
          platform_item_id: 'tb_item_1',
          sku_order_id: 'sku_order_1',
          product_id: 'prod_1',
          sku_id: 'sku_1',
          outer_sku_id: 'OUT-001',
          title: '夏季轻薄防晒衣',
          product_name: '夏季轻薄防晒衣',
          image_url: '',
          sku_spec_json: JSON.stringify({ color: '蓝色', size: 'M' }),
          quantity: 1,
          unit_price: 15990,
          unit_price_fen: 15990,
          item_pay_amount: 12990,
          item_pay_amount_fen: 12990,
          item_refund_status: 'none',
          item_shipment_status: 'not_shipped',
          shipment_status: 'not_shipped',
        },
      ],
      logistics: [
        {
          id: 'log_1',
          warehouse_id: 'wh_1',
          package_index: 1,
          company: '顺丰速运',
          company_code: 'SF',
          tracking_number: '',
          items: JSON.stringify(['item_1']),
          item_sku_ids: ['sku_1'],
          shipped_at: null,
          accepted_at: null,
          signed_at: null,
          shipment_status: 'not_shipped',
          delivery_status: '待发货',
          delivery_status_text: '待发货',
          tracking_limited: false,
          platform_callback_status: 'pending',
          platform_callback_message: '',
          platform_callback_error: null,
          callback_retry_count: 0,
          next_retry_at: null,
          intercept_status: 'none',
          intercept_requested_at: null,
          intercept_result: null,
        },
      ],
      timeline: [
        { id: 'tl_1', event: 'paid', detail: '买家付款', operator: 'system', created_at: now },
      ],
      after_sale_summary: null,
    },
    {
      id: 'ord_pdd_002',
      platform: 'pdd',
      shop_id: 'pdd_001',
      shop_name: '拼多多旗舰店',
      platform_order_id: 'PDD202607080002',
      status: 'after_sale',
      order_trade_status: 'shipped_waiting_receipt',
      order_display_status: 'after_sale_processing',
      platform_status: 'WAIT_RECEIVE',
      shipment_status: 'in_transit',
      refund_status: 'refunding',
      after_sale_status: 'processing',
      buyer_display_name: '李四',
      receiver_name_masked: '李*',
      receiver_mobile_masked: '139****5678',
      receiver_region: '广东省深圳市南山区',
      receiver_address_masked: '科技园****',
      receiver_privacy_status: 'masked',
      actual_pay_amount: 8800,
      order_total_amount: 9900,
      freight_amount: 0,
      discount_amount: 1100,
      actual_pay_amount_fen: 8800,
      order_total_amount_fen: 9900,
      freight_amount_fen: 0,
      discount_amount_fen: 1100,
      amount_unit_source: 'fen_int',
      created_at: now,
      updated_at: now,
      synced_at: now,
      raw_payload_ref: 'raw://pdd/PDD202607080002',
      mapping_schema_version: '2026-06-15-v1',
      field_source_json: JSON.stringify(fieldSources),
      field_sources: Object.values(fieldSources),
      items: [],
      logistics: [],
      timeline: [],
      after_sale_summary: {
        has_active_after_sale: true,
        has_after_sale: true,
        after_sale_status: 'processing',
        refund_status: 'refunding',
        refund_amount: 8800,
        reason_text: '买家申请退款',
        after_sale_count: 1,
      },
    },
  ];
  return base;
}

async function installApiMocks(page) {
  const orders = sampleOrders();
  await page.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (!url.pathname.startsWith('/api/')) {
      return route.continue();
    }
    const pathname = url.pathname.replace(/^\/api/, '');
    const ok = (data) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, data }),
    });
    if (pathname === '/me') {
      return ok({
        user_id: 'u_1',
        username: 'admin',
        display_name: '管理员',
        role: 'admin',
        must_change_pwd: false,
      });
    }
    if (pathname === '/orders') {
      return ok({
        total: orders.length,
        page: 1,
        page_size: 20,
        list: orders,
        status_counts: {
          pending_shipment: 1,
          after_sale_processing: 1,
          shipped_waiting_receipt: 1,
          pending_payment: 0,
        },
      });
    }
    const orderMatch = pathname.match(/^\/orders\/([^/]+)$/);
    if (orderMatch && req.method() === 'GET') {
      return ok(orders.find((o) => o.id === orderMatch[1]) || orders[0]);
    }
    if (pathname === '/shipping/records') {
      return ok({ total: orders.length, page: 1, page_size: 20, list: orders });
    }
    if (pathname === '/debug/field-mappings') {
      return ok(Object.values(JSON.parse(orders[0].field_source_json)));
    }
    if (pathname === '/notifications') {
      return ok([]);
    }
    return ok({});
  });
}

async function clickFirstVisible(page, selectors) {
  for (const sel of selectors) {
    const loc = page.locator(sel).first();
    try {
      if (await loc.count()) {
        await loc.click({ timeout: 2000 });
        return sel;
      }
    } catch {}
  }
  return null;
}

async function screenshotModel(browser, label, info, entryDir, outDir, port, keep) {
  const tag = sanitize(label);
  const p1 = path.join(outDir, `${tag}_01_order_list.png`);
  const p2 = path.join(outDir, `${tag}_02_order_detail.png`);
  const p3 = path.join(outDir, `${tag}_03_field_source.png`);
  if (keep && fs.existsSync(p1) && fs.existsSync(p2) && fs.existsSync(p3)) {
    console.log(`   [skip] ${label}: screenshots exist`);
    return;
  }

  let dev;
  try {
    dev = await startDev(entryDir, port);
  } catch (e) {
    console.error(`   [err] ${label}: ${e.message}`);
    return;
  }

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log(`     [pageerror] ${e.message.slice(0, 500)}`));
  page.on('console', (m) => {
    if (['error', 'warning'].includes(m.type())) console.log(`     [${m.type()}] ${m.text().slice(0, 500)}`);
  });

  try {
    await installApiMocks(page);
    await page.addInitScript(() => {
      localStorage.setItem('token', 'qc-token');
      localStorage.setItem('refresh_token', 'qc-refresh');
    });
    await page.goto(`${dev.url}/#/order/list`, { waitUntil: 'load', timeout: 90000 });
    await page.waitForTimeout(5000);
    const textAfterGoto = await page.evaluate(() => document.body.innerText || '').catch(() => '');
    if (!/订单管理|订单号|字段来源/.test(textAfterGoto) || /工作台/.test(textAfterGoto) && !/订单号/.test(textAfterGoto)) {
      await clickFirstVisible(page, ['text=订单管理', 'a:has-text("订单管理")', '.sidebar a:has-text("订单")']);
      await page.waitForTimeout(4000);
    }
    await page.waitForFunction(() => (document.body.innerText || '').length > 80, null, { timeout: 60000 }).catch(() => {});
    await page.screenshot({ path: p1, fullPage: true });
    console.log(`     ${path.basename(p1)}`);

    const clicked = await clickFirstVisible(page, [
      'button:has-text("详情")',
      'button:has-text("查看")',
      'text=订单详情',
      'tbody tr',
      'tr:has-text("TB202607080001")',
      '.order-row',
      '.el-table__row button',
      'tbody tr button',
    ]);
    console.log(`     detail clicked=${clicked || 'none'}`);
    await page.waitForTimeout(3000);
    await page.screenshot({ path: p2, fullPage: true });
    console.log(`     ${path.basename(p2)}`);

    const tab = await clickFirstVisible(page, [
      'text=字段来源',
      'text=调试',
      'text=来源',
      'button:has-text("字段")',
      '.el-tabs__item:has-text("字段")',
    ]);
    console.log(`     field tab clicked=${tab || 'none'}`);
    await page.waitForTimeout(2000);
    if (!tab) {
      await page.mouse.wheel(0, 2200).catch(() => {});
      await page.waitForTimeout(1000);
    }
    await page.screenshot({ path: p3, fullPage: true });
    console.log(`     ${path.basename(p3)}`);
  } catch (e) {
    console.error(`   [err] ${label}: ${e.message}`);
  } finally {
    await ctx.close();
    killTree(dev.child.pid);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const taskDir = path.join(REPO_ROOT, 'tasks', args.id);
  const mapPath = path.join(taskDir, 'model_map.json');
  if (!fs.existsSync(mapPath)) {
    console.error(`no ${mapPath}`);
    process.exit(2);
  }
  const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
  const outDir = path.join(REPO_ROOT, 'delivery', args.id, 'screenshots');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  let port = args.basePort;
  for (const [col, info] of Object.entries(map.models)) {
    if (args.only && col !== args.only) continue;
    const entryDir = path.join(taskDir, 'extracted', info.code, info.entry || '.');
    console.log(`==> ${col} (${info.code})`);
    await screenshotModel(browser, col, info, entryDir, outDir, port, args.keep);
    port += 1;
  }
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
