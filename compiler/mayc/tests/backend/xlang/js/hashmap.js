const n = 200000;
const m = new Map();
for (let i = 0; i < n; i++) m.set("k" + i * 7, i);
let sum = 0;
for (let i = 0; i < n * 2; i++) sum += m.get("k" + i) ?? 0;
console.log(sum);
