'use strict';

/** Library entry point - see cli.js for the command line wrapper. */
const { buildRoster } = require('./src/rosterBuilder');
const { validateRoster, buildCoverage } = require('./src/validate');
const { exportRoster, exportCsv } = require('./src/excel');
const constants = require('./src/constants');

module.exports = { buildRoster, validateRoster, buildCoverage, exportRoster, exportCsv, ...constants };
