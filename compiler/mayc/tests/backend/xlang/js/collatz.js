let steps = 0;
for (let seed = 1; seed <= 300000; seed++) {
    let n = seed;
    while (n > 1) { n = n % 2 === 0 ? n / 2 : n * 3 + 1; steps++; }
}
console.log(steps);
