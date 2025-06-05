#!/usr/bin/python3

import lex as lex
import yacc as yacc
import re,sys,json

import argparse
from datetime import datetime

current_date = datetime.now()
current_timestamp = current_date.strftime("%Y-%m-%d")

parser = argparse.ArgumentParser()
parser.add_argument('--action', type=str, help='an Azure action or data action')
parser.add_argument('--ultra', required=False, action="store_true", help='an Azure action or data action')
parser.add_argument('--notActions', type=str, help='a comma separated list of not actions or not data actions')
args = parser.parse_args()

# --------------------
# Lexer
# --------------------
tokens = ('TEXT', 'WILDCARD', 'SLASH')

t_WILDCARD = r'\*'
t_SLASH   = r'/'

def t_TEXT(t):
    r'[a-zA-Z.0-9]+'
    return t

t_ignore = ' \t\n'

def t_error(t):
    raise SyntaxError(f"Illegal character '{t.value[0]}'")

# --------------------
# Parser
# --------------------
def p_pattern(p):
    '''pattern : segment_list'''
    p[0] = p[1]

def p_segment_list_single(p):
    '''segment_list : segment'''
    p[0] = p[1]

def p_segment_list_multi(p):
   '''segment_list : segment_list SLASH segment'''
   # Join regex parts with literal "/" between
   p[0] = p[1] + "/" + p[3]

def p_segment(p):
   '''segment : TEXT
              | WILDCARD
              | TEXT WILDCARD
              | WILDCARD TEXT
              | TEXT WILDCARD TEXT'''
   if len(p) == 2:
       # Either a pure TEXT segment or a standalone "*"
       if p[1] == '*':
           p[0] = ".*"
       else:
           p[0] = re.escape(p[1])
   elif len(p) == 3:
       # "TEXT *" or "* TEXT"
       if p[1] == '*':
           p[0] = ".*" + re.escape(p[2])
       else:
           p[0] = re.escape(p[1]) + ".*"
   else:
       # "TEXT * TEXT"
       p[0] = re.escape(p[1]) + ".*" + re.escape(p[3])
 
def p_error(p):
     raise SyntaxError("Syntax error in input pattern")
# --------------------
# Main function
# --------------------
def expand_actions(pattern, all_actions_file='azureActions.txt'):
    if pattern.count('*') > 1:
        raise SyntaxError("Only a single wildcard '*' is allowed")
        return []
    lexer = lex.lex()
    parser = yacc.yacc()
    # Validate: wildcard not allowed in last segment unless it's /*
    pattern_parts = pattern.strip().split('/')
    try:
        if '*' in pattern_parts[-1] and pattern_parts[-1] != '*':
            raise SyntaxError("Wildcard is not allowed in the last segment unless it is a standalone '/*'")
        if len(pattern_parts) >= 1:
            last = pattern_parts[-1]
            if last not in {"Read","Action","Write","Delete","read", "write", "action", "delete", "*"}:
                raise ValueError("Last segment must be one of: read, write, action, delete, or *")
        regex_str = parser.parse(pattern, lexer=lexer)
    except SyntaxError as e:
        print("Error:", e)
        return []

    compiled_re = re.compile("^" + regex_str + "$")

    with open(all_actions_file, 'r') as f:
        actions = [line.strip() for line in f if line.strip()]

    matches = [action for action in actions if compiled_re.match(action)]
    return matches

def build_hierarchy(paths):
    from collections import defaultdict

    def insert_path(tree, parts):
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    # Build tree
    tree = {}
    for path in paths:
        parts = []
        for token in path.strip().split('/'):
            parts.extend(token.split('.'))
        insert_path(tree, parts)
    return tree

def print_hierarchy(tree, indent=0, highlight_leaves=None, highlight_lca=None, path=None):
    if path is None:
        path = []
    for key in sorted(tree.keys()):
        current_path = path + [key]
        label = key

        if highlight_leaves and current_path in highlight_leaves:
            label = f"{label} <== extreme action"
        elif highlight_lca and current_path == highlight_lca:
            label = f"{label} <== (LCA)"

        print("  " * indent + label)
        print_hierarchy(tree[key], indent + 1, highlight_leaves, highlight_lca, current_path)

def min_ultrametric_distance(tree):
    def collect_paths(node, path):
        if not node:
            return [path]
        paths = []
        for k, v in node.items():
            paths.extend(collect_paths(v, path + [k]))
        return paths

    def lca_depth(path1, path2):
        depth = 0
        for a, b in zip(path1, path2):
            if a == b:
                depth += 1
            else:
                break
        return depth

    leaf_paths = collect_paths(tree, [])
    min_lca = 9999999999
    for i in range(len(leaf_paths)):
        for j in range(i + 1, len(leaf_paths)):
            min_lca = min(min_lca, lca_depth(leaf_paths[i], leaf_paths[j]))
    return min_lca

def find_min_ultrametric_pair(tree):
    def collect_paths(node, path):
        if not node:
            return [path]
        paths = []
        for k, v in node.items():
            paths.extend(collect_paths(v, path + [k]))
        return paths

    def lca_path(path1, path2):
        common = []
        for a, b in zip(path1, path2):
            if a == b:
                common.append(a)
            else:
                break
        return common

    leaf_paths = collect_paths(tree, [])
    min_depth = 999999999
    best_pair = ([], [])
    best_lca = []

    for i in range(len(leaf_paths)):
        for j in range(i + 1, len(leaf_paths)):
            lca = lca_path(leaf_paths[i], leaf_paths[j])
            if len(lca) < min_depth:
                min_depth = len(lca)
                best_pair = (leaf_paths[i], leaf_paths[j])
                best_lca = lca
    return best_pair[0], best_pair[1], best_lca

def ultrametric_from_file(filename, all_actions_file='azureActions.txt'):
    def read_actions(file_path):
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip()]

    results = {}
    lines = read_actions(filename)
    for line in lines:
      if line!='*':
        try:
            expanded = expand_actions(line, all_actions_file=all_actions_file)
            tree = build_hierarchy(expanded)
            distance = min_ultrametric_distance(tree)
            results[line] = distance
        except Exception as e:
            results[line] = f"Error: {e}"
    return results


# --------------------
# CLI usage
# --------------------
if __name__ == '__main__':
    if args.ultra:
      res=ultrametric_from_file('wildcardActions.txt')
      print(json.dumps(res,indent=2))
      sys.exit()

    not_patterns=[]
    if args.notActions:
      not_patterns = [na.strip() for na in args.notActions.split(',') if na.strip()]
    results = set(expand_actions(args.action))
    for na in not_patterns:
      results -= set(expand_actions(na))
    #for r in sorted(results):
    #    print(r)
    print(len(results))
    #sys.exit()
    hierarchy=build_hierarchy(results)
    leaf1, leaf2, lca = find_min_ultrametric_pair(hierarchy)
    print_hierarchy(
      hierarchy,
      highlight_leaves=[leaf1, leaf2],
      highlight_lca=lca
    )
    print("")
    print("Max ultrametric distance (LCA depth):", len(lca))
    print("Representative leaf pair:")
    print("/".join(leaf1))
    print("/".join(leaf2))
