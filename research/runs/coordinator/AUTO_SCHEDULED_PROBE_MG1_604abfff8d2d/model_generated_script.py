common_prefix = 0
for i in range(64):
    if data['prefixes'][0][i] == data['prefixes'][1][i] == data['prefixes'][2][i]:
        common_prefix += 1
    else:
        break
if common_prefix == 0:
    print('Falsifier: Заголовки мають різні префікси.')
else:
    print('Hypothesis: Заголовки мають спільний префікс.')