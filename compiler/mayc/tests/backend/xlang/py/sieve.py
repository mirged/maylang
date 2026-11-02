def main():
    n = 10000000
    flags = [True] * n
    flags[0] = flags[1] = False
    i = 2
    while i * i < n:
        if flags[i]:
            for j in range(i * i, n, i):
                flags[j] = False
        i += 1
    print(sum(flags))
main()
