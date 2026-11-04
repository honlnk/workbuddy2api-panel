// Execute with ZCode's browser-use:control-browser skill in a node REPL cell.
// In a browser nodeRepl cell, define url, code, and file first, then concatenate this file.
// URL and access code must come from the user's message. No credentials belong here.
const browserPluginRoot = process.env.ZCODE_PLUGIN_ROOT ?? process.env.CLAUDE_PLUGIN_ROOT;
if (!browserPluginRoot) throw new Error("Browser plugin root is unavailable");
const { join } = await import("node:path");
const { pathToFileURL } = await import("node:url");
const { setupBrowserRuntime } = await import(pathToFileURL(join(browserPluginRoot, "scripts", "browser-client.mjs")).href);
await setupBrowserRuntime({ globals: globalThis });

if (!url?.startsWith("https://pan.quark.cn/s/")) throw new Error("Provide the user's Quark share URL");
if (!file) throw new Error("Provide an exact filename returned by the share listing");
const browser = await agent.browsers.getForUrl(url);
const tabs = await browser.tabs.list();
const match = tabs.find(t => t.url === url);
const tab = match ? await browser.tabs.get(match.id) : await browser.tabs.new();
if (!match) {
  await tab.goto(url);
  await tab.playwright.waitForLoadState({ state: "domcontentloaded" });
}
await tab.playwright.waitForTimeout(3500);

const result = await tab.playwright.evaluate(async ({ targetFile, accessCode }) => {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const rows = () => [...document.querySelectorAll("tbody tr")];
  const checked = () => rows().filter(row => row.querySelector(".ant-checkbox-input")?.checked).length;

  // Escape can cancel the host's operation. Use only the dialog's close control.
  const dialog = document.querySelector('[role="dialog"]');
  const close = dialog && [...dialog.querySelectorAll("button")].find(button => /关闭|取消|知道了|Close/i.test(button.getAttribute("aria-label") || button.textContent || ""));
  close?.click();
  await sleep(300);

  const search = document.querySelector('input[placeholder="搜索链接中的文件"]');
  if (search) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(search, targetFile);
    search.dispatchEvent(new Event("input", { bubbles: true }));
    search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(1600);
  }
  const target = rows().find(row => (row.textContent || "").includes(targetFile));
  if (!target) throw new Error("File not found; enumerate visible filenames instead of guessing");
  rows().forEach(row => { const box = row.querySelector(".ant-checkbox-input"); if (box?.checked) box.click(); });
  await sleep(400);
  const current = rows().find(row => (row.textContent || "").includes(targetFile));
  if (!current) throw new Error("Selected file row disappeared after selection reset");
  const box = current.querySelector(".ant-checkbox-input");
  if (box && !box.checked) box.click();
  await sleep(600);
  if (checked() !== 1) throw new Error("Exactly one file must be selected");
  const download = [...document.querySelectorAll("span.share-download-text, [class*='share-download']")].find(element => element.offsetParent !== null);
  if (!download) throw new Error("Visible download control not found");
  download.click();
  await sleep(2000);
  return { selected: targetFile, checked: checked(), message: document.body.innerText.match(/创建下载任务成功|文件下载超限|下载失败[^\n]*/)?.[0] || null };
}, { targetFile: file, accessCode: code });
nodeRepl.write(JSON.stringify(result));
