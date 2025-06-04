#!/usr/bin/python3

import lex as lex
import yacc as yacc
import re

# --------------------
# Lexer
# --------------------
tokens = ('TEXT', 'WILDCARD')

t_WILDCARD = r'\*'

def t_TEXT(t):
    r'[a-zA-Z.0-9/]+'
    return t

t_ignore = ' \t\n'

def t_error(t):
    raise SyntaxError(f"Illegal character '{t.value[0]}'")

# --------------------
# Parser
# --------------------
def p_pattern_single_wildcard(p):
    '''pattern : TEXT WILDCARD TEXT
               | WILDCARD TEXT
               | TEXT WILDCARD
               | WILDCARD'''
    if len(p) == 4:
        p[0] = re.escape(p[1]) + ".*" + re.escape(p[3])
    elif len(p) == 3:
        if p[1] == '*':
            p[0] = ".*" + re.escape(p[2])
        else:
            p[0] = re.escape(p[1]) + ".*"
    else:
        p[0] = ".*"

def p_pattern_text(p):
    '''pattern : TEXT'''
    p[0] = re.escape(p[1])

def p_error(p):
    raise SyntaxError("Syntax error in input pattern")

# --------------------
# Main function
# --------------------
def expand_actions(pattern, all_actions_file='allActions.txt'):
    lexer = lex.lex()
    parser = yacc.yacc()

    try:
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
    import sys
    if len(sys.argv) != 2:
        print("Usage: bel.py '<action_with_*>'")
        sys.exit(1)

    pattern = sys.argv[1]
    results = expand_actions(pattern)
    for r in results:
        print(r)

