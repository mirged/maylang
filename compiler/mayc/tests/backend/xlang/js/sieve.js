const n = 10000000;
const flags = new Array(n).fill(true);
flags[0] = flags[1] = false;
for (let i = 2; i * i < n; i++) if (flags[i]) for (let j = i * i; j < n; j += i) flags[j] = false;
let count = 0;
for (let i = 0; i < n; i++) if (flags[i]) count++;
console.log(count);
