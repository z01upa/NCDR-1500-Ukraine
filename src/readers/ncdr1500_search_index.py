"""Independent, read-only EUZ.CT search interval index verifier.

Verified for Siemens NCDR dataset EU44420940.82; not a road geometry decoder.
No original media writes, no dependence on Codex or Ollama.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import struct
import sys

HEADER_SIZE = 94
RECORD_SIZE = 14
EXPECTED_TYPE = 20

@dataclass(frozen=True)
class Node:
    index: int
    opaque_key: int
    raw_children: int
    first: int
    count: int

    @property
    def last_exclusive(self):
        return self.first + self.count

    @property
    def children(self):
        return self.raw_children // 256


def analyze_bytes(data: bytes, cl_row_count: int) -> dict:
    if cl_row_count <= 0:
        raise ValueError('CL row count must be positive')
    if len(data) < HEADER_SIZE or data[:7] != b'SIEMENS':
        raise ValueError('invalid Siemens CT file header')
    file_type, nrows = struct.unpack_from('<HI', data, 84)
    if file_type != EXPECTED_TYPE:
        raise ValueError(f'unexpected CT type {file_type}')
    if len(data) != HEADER_SIZE + nrows * RECORD_SIZE:
        raise ValueError('CT does not have 14-byte fixed records')
    nodes = []
    for index in range(nrows):
        offset = HEADER_SIZE + RECORD_SIZE*index
        key, child_word, first, count = struct.unpack_from('<IHII', data, offset)
        if not count or first + count > cl_row_count:
            raise ValueError(f'bad CL interval in CT node {index}')
        if child_word % 256:
            raise ValueError(f'CT node {index} has unknown low child flags')
        nodes.append(Node(index,key,child_word,first,count))
    if not nodes or (nodes[0].first, nodes[0].count) != (0,cl_row_count):
        raise ValueError('CT root does not cover CL table')
    spans = sorted(nodes, key=lambda n: (n.first, -n.last_exclusive, n.index))
    stack = []
    child_counts = Counter()
    roots = []
    max_depth = 0
    for node in spans:
        while stack and node.first >= stack[-1].last_exclusive:
            stack.pop()
        if stack:
            parent = stack[-1]
            if node.last_exclusive > parent.last_exclusive:
                raise ValueError(f'CT intervals cross at node {node.index}')
            child_counts[parent.index] += 1
        else:
            roots.append(node.index)
        max_depth = max(max_depth,len(stack))
        stack.append(node)
    if roots != [0]:
        raise ValueError(f'Unexpected CT index roots {roots[:5]}')
    discrepancies = [n.index for n in nodes if n.children != child_counts[n.index]]
    if discrepancies:
        raise ValueError(f'CT child counts disagree for {len(discrepancies)} nodes: {discrepancies[:5]}')
    leaf_positions = [n.first for n in nodes if n.children == 0]
    if len(leaf_positions) != cl_row_count or set(leaf_positions) != set(range(cl_row_count)):
        raise ValueError('CT leaf index positions do not bijectively cover CL rows')
    if any(n.children == 0 and n.count != 1 for n in nodes):
        raise ValueError('CT leaf node has non-singleton interval')
    return {
        'status': 'PASS', 'format': 'NCDR1500-EUZ-CT',
        'scope': 'CT tree structure and association with CL index positions ONLY; no navigation geometry or disc compatibility',
        'ct_sha256': hashlib.sha256(data).hexdigest(),
        'ct_record_count': nrows, 'cl_record_count': cl_row_count,
        'root_interval': [nodes[0].first,nodes[0].last_exclusive],
        'root_children': nodes[0].children,
        'all_child_count_words_divisible_by_256': True,
        'all_children_match_nested_intervals': True,
        'all_intervals_nested_without_crossing': True,
        'leaf_records': len(leaf_positions),
        'leaf_positions_form_complete_cl_index': True,
        'non_leaf_records': nrows-len(leaf_positions),
        'maximum_depth_observed': max_depth,
        'uncertainty': ['opaque key semantics unknown', 'whether index is used for search and its exact algorithm are not proven'],
    }


def analyze_file(path: Path, cl_count: int):
    return analyze_bytes(path.read_bytes(),cl_count)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Validate CT interval tree against CL row count, read-only')
    parser.add_argument('--ct', type=Path, required=True)
    parser.add_argument('--cl-rows', type=int, default=26949)
    parser.add_argument('--report', type=Path)
    args=parser.parse_args(argv)
    result=analyze_file(args.ct,args.cl_rows)
    result_json=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(result_json,encoding='utf-8')
    print(result_json)

if __name__=='__main__':
    main()
