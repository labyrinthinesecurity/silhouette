#!/usr/bin/python3

import lex as lex
import yacc as yacc
import re,sys

import argparse
from datetime import datetime

current_date = datetime.now()
current_timestamp = current_date.strftime("%Y-%m-%d")

parser = argparse.ArgumentParser()
parser.add_argument('--action', type=str, help='an Azure action or data action')
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
def expand_actions(pattern, all_actions_file='allActions.txt'):
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
            if last not in {"read", "write", "action", "delete", "*"}:
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

# --------------------
# CLI usage
# --------------------
if __name__ == '__main__':
    not_patterns=[]
    if args.notActions:
      not_patterns = [na.strip() for na in args.notActions.split(',') if na.strip()]
    results = set(expand_actions(args.action))
    for na in not_patterns:
      results -= set(expand_actions(na))
    for r in sorted(results):
        print(r)

