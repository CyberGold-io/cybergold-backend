"use strict";
exports.parsePositiveIntEnvOrDefault = (name, fallback) =>
  /^[1-9][0-9]*$/.test(process.env[name] || '') ? Number(process.env[name]) : fallback;
