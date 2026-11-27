import re
L = open(r'C:\urbanscenariogenerator\usg\paper\paper.tex', encoding='utf8').read().split('\n')
BS = chr(92)
pat = re.compile(re.escape(BS) + r'cite\w*\{[^}]*\}|' + re.escape(BS) + r'[a-zA-Z]+\*?|[{}~]')
def wc(a, b):
    n = 0
    for l in L[a - 1:b]:
        s = l.strip()
        if not s or s[0] == '%' or s.startswith((BS + 'reftext', BS + 'todo', 'todo')):
            continue
        n += len(pat.sub(' ', s).split())
    return n
for i, l in enumerate(L, 1):
    if l.startswith(BS + 'section') or l.startswith(BS + 'subsection'):
        print(i, l[:60])
print('intro 79-99', wc(79, 99), 'related 100-137', wc(100, 137), 'methods 138-214', wc(138, 214), 'rest 215-end', wc(215, len(L)))
