def main():
    n = 200000
    m = {}
    for i in range(n):
        m["k" + str(i * 7)] = i
    s = 0
    for i in range(n * 2):
        s += m.get("k" + str(i), 0)
    print(s)
main()
