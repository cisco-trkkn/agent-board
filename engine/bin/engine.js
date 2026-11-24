#!/usr/bin/env node
"use strict";
const { main } = require("../lib/engine/cli");
module.exports = { main };
if (require.main === module) main(process.argv.slice(2)).then((rc) => { process.exitCode = rc; });
