import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { chromium } from "playwright";

const origin = "https://glados.cloud";
const signInPage = origin + "/console/checkin";
const dates = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" });
const today = dates.format(new Date());
const verifyToday = process.env.VERIFY_BROWSER === "1";

class CheckinError extends Error {}

function loadSession() {
  let session;
  try {
    session = JSON.parse(process.env.GLADOS_BROWSER_SESSION ?? "");
  } catch {
    throw new CheckinError("需要配置 GLaDOS 云端浏览器会话。");
  } finally {
    delete process.env.GLADOS_BROWSER_SESSION;
  }

  const allowed = new Set(["gld:sess", "gld:sess.sig", "koa:sess", "koa:sess.sig"]);
  const cookies = Array.isArray(session?.cookies) ? session.cookies.filter(
    entry => entry && allowed.has(entry.name) && typeof entry.value === "string" && entry.value.length > 0,
  ) : [];
  if (!/^\d+$/.test(session?.userId ?? "") || !["gld:sess", "gld:sess.sig"].every(
    name => cookies.some(cookie => cookie.name === name),
  )) {
    throw new CheckinError("GLaDOS 会话缺少用户标识或登录凭据。");
  }
  return {
    userId: String(session.userId),
    cookies: cookies.map(({ name, value }) => ({ name, value, url: origin })),
  };
}

async function connectToChrome(profile, chrome) {
  for (let attempt = 0; attempt < 40; attempt++) {
    if (chrome.exitCode !== null) break;
    const file = await readFile(join(profile, "DevToolsActivePort"), "utf8").catch(() => "");
    const port = file.split("\n")[0];
    if (/^\d+$/.test(port)) return chromium.connectOverCDP("http://127.0.0.1:" + port);
    await wait(250);
  }
  throw new CheckinError("GitHub 运行器未能启动 Chrome。");
}

async function readPoints(page) {
  const points = await page.evaluate(async () => {
    const response = await fetch("/api/user/points", { cache: "no-store", signal: AbortSignal.timeout(10000) });
    const body = await response.json();
    return {
      code: body.code,
      rows: Array.isArray(body.history) ? body.history
        .filter(row => row.business === "system:checkin")
        .map(row => ({ id: row.id, time: Number(row.time), change: Number(row.change) })) : null,
    };
  });
  if (points.code !== 0 || points.rows === null) throw new CheckinError("无法确认 GLaDOS 的签到积分流水。");
  return points.rows.filter(row => {
    const date = new Date(row.time);
    return Number.isFinite(date.getTime()) && dates.format(date) === today;
  });
}

async function checkIn(page, expectedUser) {
  const challengeRequest = page.waitForResponse(
    response => response.url() === origin + "/api/user/checkin/challenge",
    { timeout: 22000 },
  ).then(response => response.json()).catch(() => null);
  await page.goto(signInPage, { waitUntil: "domcontentloaded", timeout: 25000 });
  if (new URL(page.url()).origin !== origin) throw new CheckinError("GLaDOS 登录页发生了意外跳转。");

  const status = await page.evaluate(async () => {
    const response = await fetch("/api/user/status", { cache: "no-store", signal: AbortSignal.timeout(10000) });
    const body = await response.json();
    return { code: body.code, userId: body.data?.userId };
  });
  if (status.code !== 0 || String(status.userId) !== expectedUser) {
    throw new CheckinError("GLaDOS 云端会话失效，或当前会话与配置账号不符。");
  }
  console.log("已确认 GLaDOS 账号登录。");

  const before = await readPoints(page);
  if (before.length > 0 && !verifyToday) {
    console.log("今天的 GLaDOS 签到已入账。");
    return;
  }

  const challenge = await challengeRequest;
  if (challenge?.code !== 0) throw new CheckinError("官网没有发出可用的签到验证。");
  if (challenge.turnstile) {
    try {
      await page.waitForFunction(() => {
        try {
          if (window.turnstile?.getResponse()) return true;
        } catch {
          // The widget can still be initializing.
        }
        return [...document.querySelectorAll('input[name="cf-turnstile-response"]')].some(field => Boolean(field.value));
      }, undefined, { timeout: 50000 });
    } catch {
      throw new CheckinError("云端浏览器未收到 Cloudflare 验证通过凭证。");
    }
    console.log("Cloudflare 签到验证已通过。");
  }

  const beforeIds = new Set(before.map(row => row.id));
  const [submitted] = await Promise.all([
    page.waitForResponse(
      response => response.url() === origin + "/api/user/checkin" && response.request().method() === "POST",
      { timeout: 20000 },
    ),
    page.getByRole("button", { name: "Checkin", exact: true }).click({ timeout: 10000 }),
  ]);
  const result = await submitted.json();
  if (result.reason === "device-mismatch") throw new CheckinError("GLaDOS 要求使用与云端 Chrome 匹配的登录会话。");
  if (result.code === 1 && before.length > 0) {
    console.log("云端签到请求已获官网响应，今日积分流水已存在。");
    return;
  }
  if (result.code !== 0) throw new CheckinError("官网没有接受本次 GLaDOS 签到。");

  const entries = await readPoints(page);
  const credit = entries.find(row => !beforeIds.has(row.id) && row.change > 0);
  if (!credit) throw new CheckinError("官网已返回签到成功，积分流水暂未确认新增。");
  console.log("GLaDOS 签到成功，新增 " + credit.change + " 积分。");
}

let profile;
let chrome;
let browser;
try {
  const session = loadSession();
  profile = await mkdtemp(join(tmpdir(), "glados-chrome-"));
  chrome = spawn("google-chrome", [
    "--user-data-dir=" + profile,
    "--remote-debugging-port=0",
    "--remote-debugging-address=127.0.0.1",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  await new Promise((resolve, reject) => {
    chrome.once("spawn", resolve);
    chrome.once("error", reject);
  });
  browser = await connectToChrome(profile, chrome);
  const context = browser.contexts()[0];
  await context.addCookies(session.cookies);
  const page = context.pages()[0] ?? await context.newPage();
  await checkIn(page, session.userId);
} catch (error) {
  console.error(error instanceof CheckinError ? error.message : "GLaDOS 浏览器任务异常结束。");
  process.exitCode = 1;
} finally {
  await browser?.close().catch(() => {});
  chrome?.kill();
  if (profile) await rm(profile, { recursive: true, force: true, maxRetries: 5 }).catch(() => {});
}
