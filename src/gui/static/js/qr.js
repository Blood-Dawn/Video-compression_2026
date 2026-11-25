/*
 * src/gui/static/js/qr.js
 *
 * A small, dependency-free QR code generator for the Pair panel: byte mode,
 * error correction level M, versions 1 to 10 (up to 213 bytes), automatic mask
 * choice. Enough for "server address + token". Nothing is sent anywhere; the
 * code is drawn locally.
 *
 *   SvcsQR.matrix("text")          -> array of rows of booleans (true = dark)
 *   SvcsQR.svg("text", {scale: 6}) -> an SVG string
 *
 * Follows the ISO/IEC 18004 construction (finder, timing and alignment
 * patterns, Reed-Solomon over GF(256) with 0x11D, format and version info).
 *
 * Author: Bloodawn (KheivenD), 2026-11-25.
 */
(function (root) {
  "use strict";

  // Level M tables, indexed by version (1..10). Index 0 unused.
  var ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  var NUM_BLOCKS = [-1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5];
  var MAX_VERSION = 10;

  function rawDataModules(ver) {
    var r = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      var na = Math.floor(ver / 7) + 2;
      r -= (25 * na - 10) * na - 55;
      if (ver >= 7) r -= 36;
    }
    return r;
  }

  function dataCodewords(ver) {
    return Math.floor(rawDataModules(ver) / 8) - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver];
  }

  // ---- Reed-Solomon over GF(256) ----------------------------------------
  function gfMul(x, y) {
    var z = 0;
    for (var i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11D);
      z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xFF;
  }

  function rsDivisor(degree) {
    var result = [];
    for (var i = 0; i < degree - 1; i++) result.push(0);
    result.push(1);
    var rt = 1;
    for (var i2 = 0; i2 < degree; i2++) {
      for (var j = 0; j < result.length; j++) {
        result[j] = gfMul(result[j], rt);
        if (j + 1 < result.length) result[j] ^= result[j + 1];
      }
      rt = gfMul(rt, 0x02);
    }
    return result;
  }

  function rsRemainder(data, divisor) {
    var result = divisor.map(function () { return 0; });
    data.forEach(function (b) {
      var factor = b ^ result.shift();
      result.push(0);
      divisor.forEach(function (coef, i) { result[i] ^= gfMul(coef, factor); });
    });
    return result;
  }

  // ---- Bits ---------------------------------------------------------------
  function utf8Bytes(text) {
    var s = unescape(encodeURIComponent(text));
    var out = [];
    for (var i = 0; i < s.length; i++) out.push(s.charCodeAt(i));
    return out;
  }

  function appendBits(bits, val, len) {
    for (var i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  }

  function encodeData(bytes, ver) {
    var bits = [];
    appendBits(bits, 0x4, 4);                         // byte mode
    appendBits(bits, bytes.length, ver < 10 ? 8 : 16);
    bytes.forEach(function (b) { appendBits(bits, b, 8); });
    var cap = dataCodewords(ver) * 8;
    appendBits(bits, 0, Math.min(4, cap - bits.length));
    appendBits(bits, 0, (8 - bits.length % 8) % 8);
    for (var pad = 0xEC; bits.length < cap; pad ^= 0xEC ^ 0x11) appendBits(bits, pad, 8);
    var words = [];
    for (var i = 0; i < bits.length; i += 8) {
      var v = 0;
      for (var k = 0; k < 8; k++) v = (v << 1) | bits[i + k];
      words.push(v);
    }
    return words;
  }

  function addEccAndInterleave(data, ver) {
    var nb = NUM_BLOCKS[ver], eccLen = ECC_PER_BLOCK[ver];
    var rawCw = Math.floor(rawDataModules(ver) / 8);
    var numShort = nb - rawCw % nb;
    var shortLen = Math.floor(rawCw / nb);
    var blocks = [], div = rsDivisor(eccLen);
    for (var i = 0, k = 0; i < nb; i++) {
      var dat = data.slice(k, k + shortLen - eccLen + (i < numShort ? 0 : 1));
      k += dat.length;
      var ecc = rsRemainder(dat, div);
      if (i < numShort) dat.push(0);
      blocks.push(dat.concat(ecc));
    }
    var result = [];
    for (var c = 0; c < blocks[0].length; c++) {
      for (var b = 0; b < blocks.length; b++) {
        if (c !== shortLen - eccLen || b >= numShort) result.push(blocks[b][c]);
      }
    }
    return result;
  }

  // ---- Matrix -------------------------------------------------------------
  function make(size, v) {
    var m = [];
    for (var i = 0; i < size; i++) { var r = []; for (var j = 0; j < size; j++) r.push(v); m.push(r); }
    return m;
  }

  function alignPositions(ver, size) {
    if (ver === 1) return [];
    var n = Math.floor(ver / 7) + 2;
    var step = (ver === 32) ? 26 : Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
    var res = [6];
    for (var pos = size - 7; res.length < n; pos -= step) res.splice(1, 0, pos);
    return res;
  }

  function build(codewords, ver) {
    var size = ver * 4 + 17;
    var mod = make(size, false), fn = make(size, false);

    function setFn(x, y, dark) { mod[y][x] = dark; fn[y][x] = true; }

    for (var i = 0; i < size; i++) { setFn(6, i, i % 2 === 0); setFn(i, 6, i % 2 === 0); }
    function finder(cx, cy) {
      for (var dy = -4; dy <= 4; dy++) for (var dx = -4; dx <= 4; dx++) {
        var dist = Math.max(Math.abs(dx), Math.abs(dy));
        var x = cx + dx, y = cy + dy;
        if (x >= 0 && x < size && y >= 0 && y < size) setFn(x, y, dist !== 2 && dist !== 4);
      }
    }
    finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
    var ap = alignPositions(ver, size), na = ap.length;
    for (var a = 0; a < na; a++) for (var b = 0; b < na; b++) {
      if ((a === 0 && b === 0) || (a === 0 && b === na - 1) || (a === na - 1 && b === 0)) continue;
      for (var dy = -2; dy <= 2; dy++) for (var dx = -2; dx <= 2; dx++)
        setFn(ap[a] + dx, ap[b] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }

    function drawFormat(m) {
      var data = (0 << 3) | m;                         // level M = 0b00
      var rem = data;
      for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      var bits = ((data << 10) | rem) ^ 0x5412;
      function bit(i) { return ((bits >>> i) & 1) !== 0; }
      for (var i2 = 0; i2 <= 5; i2++) setFn(8, i2, bit(i2));
      setFn(8, 7, bit(6)); setFn(8, 8, bit(7)); setFn(7, 8, bit(8));
      for (var i3 = 9; i3 < 15; i3++) setFn(14 - i3, 8, bit(i3));
      for (var i4 = 0; i4 < 8; i4++) setFn(size - 1 - i4, 8, bit(i4));
      for (var i5 = 8; i5 < 15; i5++) setFn(8, size - 15 + i5, bit(i5));
      setFn(8, size - 8, true);
    }
    drawFormat(0);                                      // reserve the areas

    if (ver >= 7) {
      var vrem = ver;
      for (var i6 = 0; i6 < 12; i6++) vrem = (vrem << 1) ^ ((vrem >>> 11) * 0x1F25);
      var vbits = (ver << 12) | vrem;
      for (var i7 = 0; i7 < 18; i7++) {
        var color = ((vbits >>> i7) & 1) !== 0;
        var aa = size - 11 + i7 % 3, bb = Math.floor(i7 / 3);
        setFn(aa, bb, color); setFn(bb, aa, color);
      }
    }

    // Place data bits in the zigzag order.
    var idx = 0;
    for (var right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < size; vert++) {
        for (var j = 0; j < 2; j++) {
          var x = right - j;
          var upward = ((right + 1) & 2) === 0;
          var y = upward ? size - 1 - vert : vert;
          if (!fn[y][x] && idx < codewords.length * 8) {
            mod[y][x] = ((codewords[idx >>> 3] >>> (7 - (idx & 7))) & 1) !== 0;
            idx++;
          }
        }
      }
    }

    function applyMask(m) {
      for (var y = 0; y < size; y++) for (var x = 0; x < size; x++) {
        var inv;
        switch (m) {
          case 0: inv = (x + y) % 2 === 0; break;
          case 1: inv = y % 2 === 0; break;
          case 2: inv = x % 3 === 0; break;
          case 3: inv = (x + y) % 3 === 0; break;
          case 4: inv = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
          case 5: inv = x * y % 2 + x * y % 3 === 0; break;
          case 6: inv = (x * y % 2 + x * y % 3) % 2 === 0; break;
          default: inv = ((x + y) % 2 + x * y % 3) % 2 === 0;
        }
        if (!fn[y][x] && inv) mod[y][x] = !mod[y][x];
      }
    }

    function lineScore(line) {
      var p = 0, run = 1;
      for (var i = 1; i < line.length; i++) {
        if (line[i] === line[i - 1]) { run++; if (run === 5) p += 3; else if (run > 5) p++; }
        else run = 1;
      }
      var s = line.map(function (v) { return v ? "1" : "0"; }).join("");
      var re = /(?=(00001011101|10111010000))/g, mm;
      while ((mm = re.exec(s)) !== null) { p += 40; re.lastIndex = mm.index + 1; }
      return p;
    }

    function penalty() {
      var result = 0, y, x;
      for (y = 0; y < size; y++) result += lineScore(mod[y]);
      for (x = 0; x < size; x++) {
        var col = []; for (y = 0; y < size; y++) col.push(mod[y][x]);
        result += lineScore(col);
      }
      for (y = 0; y < size - 1; y++) for (x = 0; x < size - 1; x++) {
        var c = mod[y][x];
        if (c === mod[y][x + 1] && c === mod[y + 1][x] && c === mod[y + 1][x + 1]) result += 3;
      }
      var dark = 0;
      mod.forEach(function (row) { row.forEach(function (v) { if (v) dark++; }); });
      var total = size * size;
      var k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
      return result + k * 10;
    }

    var best = 0, bestPen = Infinity;
    for (var m = 0; m < 8; m++) {
      applyMask(m); drawFormat(m);
      var pen = penalty();
      if (pen < bestPen) { bestPen = pen; best = m; }
      applyMask(m);                                    // undo (XOR)
    }
    applyMask(best); drawFormat(best);
    return mod;
  }

  function matrix(text) {
    var bytes = utf8Bytes(String(text));
    var ver = 1;
    while (ver <= MAX_VERSION) {
      var cap = dataCodewords(ver) * 8;
      var need = 4 + (ver < 10 ? 8 : 16) + bytes.length * 8;
      if (need <= cap) break;
      ver++;
    }
    if (ver > MAX_VERSION) throw new Error("Text is too long for this QR code");
    return build(addEccAndInterleave(encodeData(bytes, ver), ver), ver);
  }

  function svg(text, opts) {
    opts = opts || {};
    var scale = opts.scale || 6, quiet = opts.quiet == null ? 4 : opts.quiet;
    var m = matrix(text), n = m.length, dim = (n + quiet * 2) * scale;
    var d = [];
    for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) {
      if (m[y][x]) d.push("M" + ((x + quiet) * scale) + "," + ((y + quiet) * scale) + "h" + scale + "v" + scale + "h-" + scale + "z");
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + dim + '" height="' + dim + '" viewBox="0 0 ' + dim + " " + dim +
      '" role="img" aria-label="QR code"><rect width="100%" height="100%" fill="#fff"/><path fill="#000" d="' + d.join("") + '"/></svg>';
  }

  root.SvcsQR = { matrix: matrix, svg: svg };
  if (typeof module !== "undefined" && module.exports) module.exports = root.SvcsQR;
})(typeof window !== "undefined" ? window : globalThis);
