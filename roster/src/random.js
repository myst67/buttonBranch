'use strict';

/**
 * Small deterministic PRNG (mulberry32) so a given seed always produces the
 * same roster - handy for re-running a month and getting the same sheet.
 */
function createRng(seed) {
  let a = (seed >>> 0) || 0x9e3779b9;
  const rng = function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  rng.int = (n) => Math.floor(rng() * n);
  rng.pick = (arr) => arr[rng.int(arr.length)];
  rng.shuffled = (arr) => {
    const out = arr.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = rng.int(i + 1);
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  };
  return rng;
}

module.exports = { createRng };
