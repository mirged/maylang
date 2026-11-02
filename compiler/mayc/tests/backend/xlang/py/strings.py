def main():
    parts = []
    total = 0
    for i in range(300000):
        s = "item-" + str(i) + ";"
        total += len(s)
        parts.append(s)
    print(total, len(",".join(parts)))
main()
