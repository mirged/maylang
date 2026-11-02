def main():
    steps = 0
    for seed in range(1, 300001):
        n = seed
        while n > 1:
            n = n // 2 if n % 2 == 0 else n * 3 + 1
            steps += 1
    print(steps)
main()
