common_prefix = 0
for i in range(12):
    if data['prefixes'][0][i] == data['prefixes'][1][i] == data['prefixes'][2][i]:
        common_prefix += 1
    else:
        break
print(common_prefix)