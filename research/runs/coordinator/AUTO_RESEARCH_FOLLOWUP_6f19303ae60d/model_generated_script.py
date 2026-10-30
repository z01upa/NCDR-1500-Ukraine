common_prefix = 0
for i in range(64):
    if data['prefixes'][0][i] == data['prefixes'][1][i] == data['prefixes'][2][i]:
        common_prefix += 1
    else:
        break
if common_prefix < 64:
    print('Falsifier: The common prefix length is less than 64 bytes.')