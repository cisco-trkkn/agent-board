"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");

test("a sub that throws null, undefined or a string still gives one registry line and exit 1", () => {
  const { main } = require("../bin/registry.js");
  for (const thrown of [null, undefined, "boom\nsecond", 42]) {
    let err = "";
    const rc = main(["validate"], { load: () => () => { throw thrown; }, err: (s) => { err += s; } });
    assert.equal(rc, 1);
    assert.match(err, /^registry: validate: [^\n]*\n$/);
  }
  let err = "";
  const rc = main(["validate"], { load: () => () => { throw Object.assign(new Error("x"), { code: 3 }); }, err: (s) => { err += s; } });
  assert.equal(rc, 3);
  assert.equal(err, "registry: validate: x\n");
});
