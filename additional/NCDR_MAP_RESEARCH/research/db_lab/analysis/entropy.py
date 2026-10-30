from collections import Counter
import math

def profile(data):
    if not data: return {"length": 0, "entropy": 0.0, "zero_ratio": 0.0, "unique_bytes": 0}
    counts = Counter(data); n = len(data)
    entropy = -sum((v/n)*math.log2(v/n) for v in counts.values())
    return {"length": n, "entropy": round(entropy, 6),
            "zero_ratio": round(counts.get(0, 0)/n, 6), "unique_bytes": len(counts)}
