const parts = [];
let total = 0;
for (let i = 0; i < 300000; i++) { const s = "item-" + String(i) + ";"; total += s.length; parts.push(s); }
console.log(total, parts.join(",").length);
