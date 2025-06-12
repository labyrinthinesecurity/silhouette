#!/usr/bin/bash
jq -r '
  to_entries[]
  | .value.dataActions_dict
  | to_entries[]
  | .value[]
' spnperms.json | grep '\*' | sort -u > customerWildcardDataActions.txt

jq -r '
  to_entries[]
  | .value.actions_dict
  | to_entries[]
  | .value[]
' spnperms.json | grep '\*' | sort -u > customerWildcardActions.txt

