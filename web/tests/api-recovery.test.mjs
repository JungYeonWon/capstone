import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const compiled = ts.transpileModule(fs.readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
let sequence = 0;
const freshClient = () => import("data:text/javascript;base64," + Buffer.from(compiled + "\n// instance " + ++sequence).toString("base64"));

test("concurrent identical AI requests share one call and a failed request can be retried", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  globalThis.fetch = async url => {
    if (String(url).endsWith("/auth/csrf")) return Response.json({ csrf_token: "fictional" });
    calls++;
    if (calls === 1) { await pending; return Response.json({ detail: "일시 오류" }, { status: 503 }); }
    return Response.json({ result: "recovered" });
  };
  try {
    const { api, ApiError } = await freshClient();
    const one = api.post("/contracts/1/clause-review/analyze", { files: [] });
    const two = api.post("/contracts/1/clause-review/analyze", { files: [] });
    assert.equal(one, two);
    release();
    await assert.rejects(one, error => error instanceof ApiError && error.retryable);
    assert.equal(calls, 1);
    assert.deepEqual(await api.post("/contracts/1/clause-review/analyze", { files: [] }), { result: "recovered" });
    assert.equal(calls, 2);
  } finally { globalThis.fetch = original; }
});

test("credential errors do not suggest retry and network failures retain a clear recovery message", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith("/auth/csrf")
    ? Response.json({ csrf_token: "fictional" })
    : Response.json({ detail: "API 키를 확인하세요." }, { status: 503, headers: { "X-AI-Retryable": "false" } });
  try {
    const { api } = await freshClient();
    await assert.rejects(api.post("/contracts/1/clause-review/analyze", {}), error => !error.retryable);
    globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
    await assert.rejects(api.put("/contracts/1/workspace/builder", {}), error =>
      error.retryable && error.status === 0 && error.message.includes("현재 입력을 유지"));
  } finally { globalThis.fetch = original; }
});
