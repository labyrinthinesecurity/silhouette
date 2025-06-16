#!/usr/bin/python3

import lex as lex
import yacc as yacc
import re,sys,json
import argparse
from datetime import datetime
import functools
print = functools.partial(print, flush=True)    # forces flush=True for all print() calls

current_date = datetime.now()
current_timestamp = current_date.strftime("%Y-%m-%d")

parser = argparse.ArgumentParser()
parser.add_argument('--action', type=str, help='an Azure action, eg Microsoft.*/read')
parser.add_argument('--discover', required=False, action="store_true", help='generate wildcards and discover extreme action pairs from official azure actions. Run extractAzureActions.sh first!')
parser.add_argument('--evaluate', required=False, action="store_true", help='count explicit actions for each customer wildcard action. Run extractCustomerWildcardActions.sh first!')
parser.add_argument('--notActions', type=str, help='a comma separated list of not actions')
args = parser.parse_args()


# --------------------
# Lexer
# --------------------
tokens = ('TEXT', 'WILDCARD', 'SLASH')

t_WILDCARD = r'\*'
t_SLASH   = r'/'

def t_TEXT(t):
    r'[a-zA-Z0-9.-_{}$]+'
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

    def lca_depth_and_path(path1, path2):
        depth = 0
        for a, b in zip(path1, path2):
            if a == b:
                depth += 1
            else:
                break
        return depth, path1[:depth]

    leaf_paths = collect_paths(tree, [])
    min_lca = float('inf')
    min_pair = None
    min_lca_path = None

    for i in range(len(leaf_paths)):
        for j in range(i + 1, len(leaf_paths)):
            depth, lca_path = lca_depth_and_path(leaf_paths[i], leaf_paths[j])
            if depth < min_lca:
                min_lca = depth
                min_pair = ('/'.join(leaf_paths[i]), '/'.join(leaf_paths[j]))
                min_lca_path = lca_path

    return min_lca, min_pair, min_lca_path

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
            distance,minpair,minpath = min_ultrametric_distance(tree)
            if distance < 100:
              left_pair=minpair[0]
              right_pair=minpair[1]
              results[line] = str(distance)+";"+str(left_pair)+";"+str(right_pair)
        except Exception as e:
            results[line] = f"Error: {e}"
    return results

import random

def optimize_wildcard_ultradist(action, pop, generations, all_actions_file='azureActions.txt'):
    """
    Given a concrete action string `action`, runs a genetic algorithm to find a single-wildcard
    pattern that maximizes the ultrametric distance among its expanded actions.

    - pop: population size (number of (x,y) pairs per generation)
    - generations: number of GA generations to run
    - all_actions_file: path to the file with all Az actions for expansion

    Returns:
        best_pattern (str): the wildcarded action string with maximal ultradistance
        best_distance (int): the corresponding maximal ultrametric distance
    """
    # Cache: maps (x, y) -> ultrametric distance
    cache = {}

    length = len(action)

    def compute_ultra_for_xy(x, y):
        # If seen before, return cached
        pattern = action[:x] + '*' + action[y:]
        if (x, y) in cache:
            return cache[(x, y)][0],pattern,x,y
        # Build wildcard pattern by replacing action[x:y] -> '*'
        # Find start of last segment
        last_slash = action.rfind('/')
        #print("U",pattern,y,last_slash,x,action[:x-1],len(action))
        if last_slash == -1:
          return float('inf'),pattern,x,y  # Invalid action format
        # Prevent wildcard from fully or partially cutting into the last segment (unless it replaces it)
#        pattern_parts = pattern.strip().split('/')
#        if '*' in pattern_parts[-1] and pattern_parts[-1] != '*':
        if y > last_slash and x < len(action):
        #if y > last_slash and ('/' in action[:x-1]):
          #print("P",pattern,y,last_slash,x,action[:x-1],len(action))
          return float('inf'),pattern,x,y  # Invalid wildcard placement

        # Expand and compute ultradistance
        expanded = expand_actions(pattern, all_actions_file=all_actions_file)
        if (not expanded) or (len(expanded) == 1):
            dist = float('inf')
            bpair = (None,None)
            tree = None
        else:
            tree = build_hierarchy(expanded)
            dist,bpair,_ = min_ultrametric_distance(tree)
            #print("MIN EX",pattern,len(expanded),expanded,dist,bpair)
            #print("TREE")
            #print(tree)
        cache[(x, y)] = (dist,bpair)
        return dist,pattern,x,y

    # Initialize population: list of (x, y) with 0 <= x < y <= length
    population = []
    N=pop

    last_slash = action.rfind('/')
    first_dot = action.find('.')
    
    # Ensure wildcard does not partially replace the last segment
    def is_valid_wildcard(x, y):
    # Allow wildcard only if:
    # - it ends before the last segment: y <= last_slash
    # - or it fully replaces the last segment: x <= last_slash and y == len(action)
      return (y <= last_slash or (x <= last_slash and y == len(action))) and (x > first_dot + 3)

    population = []
    while len(population) < N:
      x = random.randint(0, len(action) - 2)
      y = random.randint(x + 1, len(action))
      if not is_valid_wildcard(x, y):
        continue
      population.append((x, y))

    best_pair = None
    best_distance = float('inf')

    for gen in range(generations):
        #print("generation:",gen)
        #print("population:",len(population),population)
        # Evaluate fitness for all individuals
        ultras= [(compute_ultra_for_xy(x, y), (x, y)) for (x, y) in population]
        #print(ultras)
        fitness = [ udist[0] for udist in ultras ]
        #print()
        #for f in fitness:
        #  print(">",f)
        fitness.sort(reverse=False, key=lambda t: t[0])
        # Track global best
        #print(fitness)
        #print("F0",fitness[0])
        top_dist = fitness[0][0]
        top_pair = (fitness[0][2],fitness[0][3])
#        top_dist, _, top_pair = fitness[0]
        if top_dist <  best_distance:
            best_distance = top_dist
            best_pair = top_pair

        # Selection: take top 50%
        survivors = [(left,right) for (_, pat, left, right) in fitness[: N // 2]]

        # Reproduce: fill new population by mutating survivors
        new_population = survivors.copy()
        while len(new_population) < N:
            parent = random.choice(survivors)
            x_parent, y_parent = parent

            # Mutation: tweak x or y by ±1..3 positions, then clamp
            if random.random() < 0.4:
                # mutate x
                delta = random.randint(-4, 4)
                x_new = max(0, min(length - 3, x_parent + delta))
                # ensure y_new > x_new
                y_new = max(x_new + 1, y_parent)
                if y_new > length:
                    y_new = length
                    if x_new >= y_new:
                        x_new = y_new - 1
                # Safety net: ensure wildcard does not intrude into the last segment unless replacing it entirely
                if not is_valid_wildcard(x_new, y_new):
                  continue 
                new_population.append((x_new, y_new))
            else:
                # mutate y
                delta = random.randint(-20, 20)
                y_new = max(1, min(length, y_parent + delta))
                # ensure y_new > x_parent
                if y_new <= x_parent:
                    y_new = x_parent + 1
                if y_new > length:
                    y_new = length
                if not is_valid_wildcard(x_parent, y_new):
                  continue
                new_population.append((x_parent, y_new))

        population = new_population
    # Build best pattern string
    if best_pair:
      x_best, y_best = best_pair
      best_pattern = action[:x_best] + '*' + action[y_best:]
      if (x_best,y_best) not in cache:
        compute_ultra_for_xy(x_best, y_best)
      return best_pattern, best_distance,cache[(x_best,y_best)]
    else:
      #print("NONE for",action,population)
      #print()
      #for ff in fitness:
      #  print(ff)
      #print()
      return None,None,None

# --------------------
# CLI usage
# --------------------
if __name__ == '__main__':
    if args.discover:
      print("wildcard;diameter;left_pair;right_pair")
      with open('azureActions.txt', 'r') as f:
          actions = [line.strip() for line in f if line.strip()]
      for action in actions:
        genetics=optimize_wildcard_ultradist(action, pop=40, generations=40)
        if genetics[0] is not None:
          print(f"{genetics[0]};{genetics[1]};{genetics[2][1][0]};{genetics[2][1][1]}")
        else:
          print(f"{action};;{action};{action}")
      sys.exit()                            
    if args.evaluate:
      res=ultrametric_from_file('customerWildcardActions.txt')
      print("wildcard;diameter;left_pair;right_pair")
      for r in res:
        print(r+";"+res[r])
      sys.exit()
    if args.action: 
      not_patterns=[]
      if args.notActions:
        not_patterns = [na.strip() for na in args.notActions.split(',') if na.strip()]
      results = set(expand_actions(args.action))
      for na in not_patterns:
        results -= set(expand_actions(na))
      print(len(results))
      for r in results:
        print(r)
      sys.exit()
